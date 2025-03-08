import time
import datetime
import glob
import os
import shutil
import subprocess
import sys

import openmm.unit as unit
import openmm.app as openmm_app

from gamd import utils as utils
from gamd.DebugLogger import DebugLogger, NoOpDebugLogger
from gamd.GamdLogger import GamdLogger, NoOpGamdLogger


def create_output_directories(directories, overwrite_output=False):
    if overwrite_output:
        for directory in directories:
            if os.path.exists(directory):
                print("Deleting old output directory:", directory)
                os.system('rm -r %s' % directory)

    for directory in directories:
        os.makedirs(directory, 0o755)


def get_global_variable_names(integrator):
    for index in range(0, integrator.getNumGlobalVariables()):
        print(integrator.getGlobalVariableName(index))


def print_global_variables(integrator):
    for index in range(0, integrator.getNumGlobalVariables()):
        name = integrator.getGlobalVariableName(index)
        value = integrator.getGlobalVariableByName(name)
        print(name + ":  " + str(value))


def write_gamd_production_restart_file(output_directory, integrator,
                                       first_boost_type, second_boost_type):
    """
    Writes out the current GaMD statistics (e.g. Vmax, Vmin, Vavg, sigmaV, thresholdE, k0)
    so a future run can reload these values if needed.
    """
    gamd_prod_restart_filename = os.path.join(output_directory, "gamd-restart.dat")
    values = integrator.get_statistics()

    with open(gamd_prod_restart_filename, "w") as gamd_prod_restart_file:
        for key in values.keys():
            gamd_prod_restart_file.write(key + "=" + str(values[key]) + "\n")


def get_config_and_simulation_values(gamd_simulation, config):
    output_directory = config.outputs.directory
    overwrite_output = config.outputs.overwrite_output
    system = gamd_simulation.system
    simulation = gamd_simulation.simulation
    integrator = gamd_simulation.integrator
    dt = config.integrator.dt
    ntcmdprep = config.integrator.number_of_steps.conventional_md_prep
    ntcmd = config.integrator.number_of_steps.conventional_md
    ntebprep = config.integrator.number_of_steps.gamd_equilibration_prep
    nteb = config.integrator.number_of_steps.gamd_equilibration
    last_step_of_equilibration = ntcmd + nteb
    nstlim = config.integrator.number_of_steps.total_simulation_length
    ntave = config.integrator.number_of_steps.averaging_window_interval

    return [output_directory, overwrite_output, system, simulation, dt,
            integrator, ntcmdprep, ntcmd, ntebprep,
            nteb, last_step_of_equilibration, nstlim, ntave]


def print_runtime_information(start_date_time, dt, nstlim, current_step):
    end_date_time = datetime.datetime.now()
    time_difference = end_date_time - start_date_time
    if time_difference.seconds > 0:
        steps_per_second = (nstlim - current_step) / time_difference.seconds
    else:
        steps_per_second = 0

    daily_execution_rate = (steps_per_second * 3600 * 24 * dt)

    print("Start Time: \t", start_date_time.strftime("%b-%d-%Y    %H:%M:%S"))
    print("End Time: \t", end_date_time.strftime("%b-%d-%Y    %H:%M:%S"))
    print("Execution rate for this run:  ", str(steps_per_second),
          " steps per second.")
    print("Daily execution rate:         ",
          str(daily_execution_rate.value_in_unit(unit.nanoseconds)),
          " ns per day.")


class RunningRates:

    def __init__(self, number_of_simulation_steps: int, save_rate: int,
                 reporting_rate: int,
                 debugging_enabled: bool = False,
                 debugging_step_function=None) -> None:
        """
        The save_rate determines the rate at which to write out DCD/PDB,
        checkpoint, coordinates, and GaMD logs. The value of save_rate
        should evenly divide the number_of_simulation_steps.

        The reporting_rate determines how often we write the state-data.log
        (and debug logs if debugging). The value of reporting_rate
        should evenly divide the number_of_simulation_steps.

        If debugging is enabled, one rate should be a multiple of the other.

        The 'batch_run_rate' is how many steps OpenMM executes at a time.
        """
        if ((number_of_simulation_steps % save_rate) != 0 and
                (number_of_simulation_steps % reporting_rate) != 0):
            raise ValueError("RunningRates:  The save_rate and reporting_rate "
                             "should evenly divide into the total steps.")

        if debugging_enabled and not (((save_rate % reporting_rate) == 0) or
                                      ((reporting_rate % save_rate) == 0)):
            raise ValueError("RunningRates:  When debugging is enabled, "
                             "save_rate/reporting_rate must be multiples.")

        self.debugging_step_function = debugging_step_function
        self.custom_debugging_function = callable(debugging_step_function)

        self.save_rate = save_rate
        self.reporting_rate = reporting_rate
        self.number_of_simulation_steps = number_of_simulation_steps
        self.debugging_enabled = debugging_enabled

        # batch_run_rate logic
        if debugging_enabled:
            if save_rate <= reporting_rate:
                self.batch_run_rate = save_rate
            else:
                self.batch_run_rate = reporting_rate
        else:
            self.batch_run_rate = self.save_rate

    def get_save_rate(self):
        return self.save_rate

    def get_reporting_rate(self):
        return self.reporting_rate

    def is_save_step(self, step):
        return (step % self.save_rate) == 0

    def is_reporting_step(self, step):
        return (step % self.reporting_rate) == 0

    def get_batch_run_rate(self):
        return self.batch_run_rate

    def is_debugging_step(self, step):
        if self.custom_debugging_function:
            return self.debugging_step_function(step)
        else:
            return (step % self.reporting_rate) == 0

    def get_batch_run_range(self):
        """
        Yields frames from 1..(total_steps // batch_run_rate)
        """
        return range(1, self.number_of_simulation_steps //
                     self.get_batch_run_rate() + 1)

    def get_restart_step(self, integrator):
        """
        Figure out which batch-frame we last completed by reading integrator.stepCount
        """
        current_steps = integrator.getGlobalVariableByName("stepCount")
        start_frame = int(round(current_steps / self.get_batch_run_rate()))
        return start_frame

    def get_restart_batch_run_range(self, integrator):
        """
        Yields frames from (last-completed) .. end
        """
        return range(self.get_restart_step(integrator) + 1,
                     self.number_of_simulation_steps //
                     self.get_batch_run_rate() + 1)

    def get_step_from_frame(self, frame):
        """
        Convert a batch-frame index to the absolute step count
        """
        return frame * self.get_batch_run_rate()


class Runner:
    def __init__(self, config, gamd_simulation, debug):
        self.config = config
        self.gamd_simulation = gamd_simulation
        self.debug = debug

        nstlim = self.config.integrator.number_of_steps.total_simulation_length
        self.chunk_size = self.config.outputs.reporting.compute_chunk_size()

        # Decide the initial RunningRates
        if debug:
            self.running_rates = RunningRates(nstlim, self.chunk_size, 1, True)
        else:
            self.running_rates = RunningRates(nstlim, self.chunk_size,
                                              self.chunk_size, False)

        self.gamd_logger_enabled = True
        self.gamd_reweighting_logger_enabled = False
        self.state_data_reporter_enabled = False
        self.gamd_dat_reporter_enabled = False

    def run_post_simulation(self, temperature, output_directory,
                            production_starting_frame):
        """
        Hook for any post-simulation tasks (analysis, reweighting, etc.).
        """
        return

    def save_initial_configuration(self, production_logging_start_step,
                                   temperature):
        """
        Example method to serialize config or record initial settings.
        """
        config_filename = os.path.join(self.config.outputs.directory,
                                       "input.xml")
        prodstartstep_filename = os.path.join(self.config.outputs.directory,
                                              "production-start-step.txt")
        temperature_filename = os.path.join(self.config.outputs.directory,
                                            "temperature.dat")

        self.config.serialize(config_filename)

        with open(temperature_filename, "w") as temperature_file:
            temperature_file.write(str(temperature))

        with open(prodstartstep_filename, "w") as prodstartstep_file:
            prodstartstep_file.write(str(production_logging_start_step))

    def register_trajectory_reporter(self, restart):
        """
        Add the DCD or PDB reporter for coordinates.
        """
        simulation = self.gamd_simulation.simulation
        traj_reporter = self.gamd_simulation.traj_reporter
        output_directory = self.config.outputs.directory
        extension = self.config.outputs.reporting.coordinates_file_type

        if restart:
            traj_name = os.path.join(output_directory, f'output_restart.{extension}')
            traj_append = False
        else:
            traj_name = os.path.join(output_directory, f'output.{extension}')
            traj_append = False

        if traj_reporter == openmm_app.DCDReporter:
            simulation.reporters.append(
                traj_reporter(traj_name,
                              self.config.outputs.reporting.coordinates_interval,
                              append=traj_append)
            )
        elif traj_reporter == openmm_app.PDBReporter:
            simulation.reporters.append(
                traj_reporter(traj_name,
                              self.config.outputs.reporting.coordinates_interval)
            )

    def register_state_data_reporter(self, restart):
        """
        Adds the StateDataReporter to log energies, temperature, etc.
        """
        if self.state_data_reporter_enabled:
            simulation = self.gamd_simulation.simulation
            output_directory = self.config.outputs.directory
            system = self.gamd_simulation.system

            if restart:
                # Unique log filename for each restart
                state_data_restart_files_glob = os.path.join(
                    output_directory, 'state-data.restart*.log')
                state_data_restarts_list = glob.glob(state_data_restart_files_glob)
                restart_index = len(state_data_restarts_list) + 1
                state_data_name = os.path.join(
                    output_directory, 'state-data.restart%d.log' % restart_index)
            else:
                state_data_name = os.path.join(output_directory, 'state-data.log')

            simulation.reporters.append(
                utils.ExpandedStateDataReporter(
                    system,
                    state_data_name,
                    self.config.outputs.reporting.energy_interval,
                    step=True,
                    brokenOutForceEnergies=True,
                    temperature=True,
                    potentialEnergy=True,
                    totalEnergy=True,
                    volume=True
                )
            )

    def register_gamd_data_reporter(self, restart):
        """
        Optionally writes out a CSV with GaMD variables each step.
        """
        if self.gamd_dat_reporter_enabled:
            simulation = self.gamd_simulation.simulation
            output_directory = self.config.outputs.directory
            gamd_running_dat_filename = os.path.join(output_directory, "gamd-running.csv")
            integrator = self.gamd_simulation.integrator

            if restart:
                write_mode = "a"
            else:
                write_mode = "w"

            gamd_dat_reporter = utils.GamdDatReporter(
                gamd_running_dat_filename, write_mode, integrator
            )
            simulation.reporters.append(gamd_dat_reporter)

    def register_gamd_logger(self, restart):
        """
        The plain-text GaMD log for energies and boosts each save interval.
        """
        if self.gamd_logger_enabled:
            output_directory = self.config.outputs.directory
            gamd_log_filename = os.path.join(output_directory, "gamd.log")
            integrator = self.gamd_simulation.integrator
            simulation = self.gamd_simulation.simulation

            file_exists = os.path.exists(gamd_log_filename)
            write_mode = "a" if file_exists else "w"

            gamd_logger = GamdLogger(
                gamd_log_filename,
                write_mode,
                integrator,
                simulation,
                self.gamd_simulation.first_boost_type,
                self.gamd_simulation.first_boost_group,
                self.gamd_simulation.second_boost_type,
                self.gamd_simulation.second_boost_group
            )

            if not file_exists:
                gamd_logger.write_header()
        else:
            gamd_logger = NoOpGamdLogger()
        return gamd_logger

    def register_gamd_reweighting_logger(self, restart):
        """
        A separate log for reweighting data if desired.
        """
        if self.gamd_reweighting_logger_enabled:
            output_directory = self.config.outputs.directory
            integrator = self.gamd_simulation.integrator
            simulation = self.gamd_simulation.simulation
            gamd_reweighting_filename = os.path.join(
                output_directory, "gamd-reweighting.log"
            )

            write_mode = "a" if restart else "w"
            gamd_reweighting_logger = GamdLogger(
                gamd_reweighting_filename,
                write_mode,
                integrator,
                simulation,
                self.gamd_simulation.first_boost_type,
                self.gamd_simulation.first_boost_group,
                self.gamd_simulation.second_boost_type,
                self.gamd_simulation.second_boost_group
            )
            if not restart:
                gamd_reweighting_logger.write_header()
        else:
            gamd_reweighting_logger = NoOpGamdLogger()
        return gamd_reweighting_logger

    def register_debug_logger(self, restart):
        """
        Debug logger for integrator global variables, if self.debug = True.
        """
        output_directory = self.config.outputs.directory
        integrator = self.gamd_simulation.integrator
        debug_filename = os.path.join(output_directory, "debug.csv")
        write_mode = "a" if restart else "w"

        if self.debug:
            ignore_fields = {
                "stageOneIfValueIsZeroOrNegative",
                "stageTwoIfValueIsZeroOrNegative",
                "stageThreeIfValueIsZeroOrNegative",
                "stageFourIfValueIsZeroOrNegative",
                "stageFiveIfValueIsZeroOrNegative",
                "thermal_energy",
                "collision_rate",
                "vscale",
                "fscale",
                "noisescale",
            }

            debug_logger = DebugLogger(debug_filename, write_mode, ignore_fields)
            print("Debugging enabled.")
            int_algorithm_filename = os.path.join(output_directory,
                                                  "integration-algorithm.txt")
            debug_logger.write_integration_algorithm_to_file(
                int_algorithm_filename, integrator
            )
            debug_logger.write_global_variables_headers(integrator)
        else:
            debug_logger = NoOpDebugLogger()

        return debug_logger

    def run(self, restart=False):
        """
        Main entry point to run (or extend) the simulation.
        """
        simulation = self.gamd_simulation.simulation
        integrator = self.gamd_simulation.integrator
        dt = self.config.integrator.dt  # needed for state_time -> steps
        output_directory = self.config.outputs.directory
        overwrite_output = self.config.outputs.overwrite_output

        # Some key parameters from config:
        ntcmdprep = self.config.integrator.number_of_steps.conventional_md_prep
        ntcmd = self.config.integrator.number_of_steps.conventional_md
        ntebprep = self.config.integrator.number_of_steps.gamd_equilibration_prep
        nteb = self.config.integrator.number_of_steps.gamd_equilibration
        chunk_size = self.chunk_size
        last_step_of_equilibration = ntcmd + nteb
        nstlim = self.config.integrator.number_of_steps.total_simulation_length

        # Our checkpoint file
        restart_checkpoint_filename = os.path.join(output_directory, "gamd_restart.checkpoint")

        if not restart:
            # Fresh run: Create output directories, start from step 0
            create_output_directories([output_directory], overwrite_output)
            old_step_count = 0
            current_step = 0
            is_extension_run = False
            running_range = self.running_rates.get_batch_run_range()

            print("[DEBUG] Normal (fresh) run batch_run_range =",
                  list(running_range))
        else:
            # Restarting from checkpoint
            simulation.loadCheckpoint(restart_checkpoint_filename)
            old_step_count = int(integrator.getGlobalVariableByName("stepCount"))
            state = simulation.context.getState(getPositions=True,
                                                getVelocities=True)
            # If we prefer, we can read time from state_time:
            # state_time = state.getTime().value_in_unit(unit.picoseconds)
            # integrator_dt = dt.value_in_unit(unit.picoseconds)
            # current_step = int(round(state_time / integrator_dt))

            current_step = old_step_count
            simulation.currentStep = old_step_count
            os.makedirs(output_directory, exist_ok=True)

            # See if we want to extend further
            extension_steps = self.config.integrator.number_of_steps.extension_steps
            if extension_steps > 0:
                is_extension_run = True
                new_nstlim = old_step_count + extension_steps
                print(f"[Restart Mode] Current step = {current_step}. "
                      f"Overriding nstlim to {new_nstlim} using extension-steps={extension_steps}.")

                # Update integrator in place
                integrator.setGlobalVariableByName("stepCount", old_step_count)

                # Force stage 5 if you want to remain in production
                integrator.stage_5_start = old_step_count
                integrator.stage_5_end = new_nstlim
                integrator.setGlobalVariableByName("stage", 5)

                # Optionally reload GaMD stats from file:
                gamd_stats_file = os.path.join(output_directory, "gamd-restart.dat")
                if os.path.exists(gamd_stats_file):
                    load_gamd_stats_from_file(integrator, gamd_stats_file)

                # Reinitialize context to ensure global variables are updated
                simulation.context.reinitialize(preserveState=True)
                simulation.currentStep = old_step_count

                # Update runner's total steps
                self.config.integrator.number_of_steps.total_simulation_length = new_nstlim
                self.running_rates = RunningRates(
                    new_nstlim,
                    self.chunk_size,
                    1 if self.debug else self.chunk_size,
                    debugging_enabled=self.debug
                )
                running_range = self.running_rates.get_restart_batch_run_range(integrator)

                debug_range_list = list(running_range)
                print("[DEBUG] Extension run batch_run_range =", debug_range_list)
                if len(debug_range_list) == 0:
                    print("[DEBUG] WARNING: The batch run range is empty. No steps left to run!")
            else:
                # Normal restart with no extension
                is_extension_run = False
                running_range = self.running_rates.get_restart_batch_run_range(integrator)
                print("[DEBUG] Restart run (no extension). Batch run range =",
                      list(running_range))

        # Register all reporters/loggers
        self.register_trajectory_reporter(restart)
        self.register_state_data_reporter(restart)
        self.register_gamd_data_reporter(restart)
        debug_logger = self.register_debug_logger(restart)
        gamd_logger = self.register_gamd_logger(restart)
        gamd_reweighting_logger = self.register_gamd_reweighting_logger(restart)

        # This offset can be used for reweighting frames
        reweighting_offset = 0
        production_logging_start_step = (ntcmd + nteb +
                                         (self.running_rates.get_batch_run_rate()
                                          * reweighting_offset))

        self.save_initial_configuration(
            production_logging_start_step,
            self.config.temperature
        )

        print("Running: \t",
              str(integrator.get_total_simulation_steps() - current_step),
              " steps")

        # Debug
        try:
            print("[DEBUG] integrator stage =", integrator.getGlobalVariableByName("stage"))
            print("[DEBUG] stage_5_start =", getattr(integrator, "stage_5_start", None))
            print("[DEBUG] stage_5_end   =", getattr(integrator, "stage_5_end", None))
        except Exception as e:
            print("[DEBUG] Could not read stage/5_start/5_end:", e)

        start_date_time = datetime.datetime.now()
        batch_run_rate = self.running_rates.get_batch_run_rate()

        # --------------------------
        #  MAIN SIMULATION LOOP
        # --------------------------
        for batch_frame in running_range:
            step = self.running_rates.get_step_from_frame(batch_frame)

            # Save checkpoint at intervals
            if self.running_rates.is_save_step(step):
                simulation.saveCheckpoint(restart_checkpoint_filename)

            # Record energies for GaMD
            gamd_logger.mark_energies()
            if self.running_rates.is_save_step(step):
                gamd_reweighting_logger.mark_energies()

            try:
                simulation.step(batch_run_rate)

                if self.running_rates.is_debugging_step(batch_frame):
                    debug_logger.write_global_variables_values(integrator)

                if self.running_rates.is_save_step(step):
                    gamd_logger.write_to_gamd_log(step)
                    if step >= production_logging_start_step:
                        gamd_reweighting_logger.write_to_gamd_log(step)

            except Exception as e:
                print("Failure on step " + str(step))
                print(e)
                gamd_logger.close()
                gamd_reweighting_logger.close()
                debug_logger.print_global_variables_to_screen(integrator)
                debug_logger.write_global_variables_values(integrator)
                debug_logger.close()
                sys.exit(2)

            # If we are not in an extension run, we can write a mid-sim GaMD restart
            # e.g. right after Stage 4 completes or at last_step_of_equilibration:
            if (not is_extension_run) and (step == last_step_of_equilibration):
                write_gamd_production_restart_file(
                    output_directory,
                    integrator,
                    self.gamd_simulation.first_boost_type,
                    self.gamd_simulation.second_boost_type
                )

        # --------------------------
        #  DONE: Cleanup
        # --------------------------
        gamd_logger.close()
        gamd_reweighting_logger.close()
        debug_logger.close()

        # Final checkpoint
        simulation.saveCheckpoint(restart_checkpoint_filename)

        # Print timing stats
        current_step = int(integrator.getGlobalVariableByName("stepCount"))
        print_runtime_information(start_date_time, dt, nstlim, current_step)

        production_starting_frame = (((ntcmd + nteb) / chunk_size) +
                                     reweighting_offset)

        # Call optional post-sim step
        self.run_post_simulation(
            self.config.temperature,
            output_directory,
            production_starting_frame
        )


class DeveloperRunner(Runner):
    def __init__(self, config, gamd_simulation, debug):
        super().__init__(config, gamd_simulation, debug)
        self.gamd_logger_enabled = True
        self.gamd_reweighting_logger_enabled = True
        self.state_data_reporter_enabled = True
        self.gamd_dat_reporter_enabled = True


class NoLogRunner(Runner):
    def __init__(self, config, gamd_simulation, debug):
        super().__init__(config, gamd_simulation, debug)
        self.gamd_logger_enabled = False
        self.gamd_reweighting_logger_enabled = False
        self.state_data_reporter_enabled = False
        self.gamd_dat_reporter_enabled = False


def dump_gamd_stats(integrator):
    """
    Reads statistics (Vmax, Vmin, Vavg, sigmaV, thresholdE, k0, etc.)
    from the integrator, returning them in a dictionary.
    """
    stats = integrator.get_statistics()  # returns a dict
    print("Integrator stats at end of run:", stats)
    return stats


def load_gamd_stats(integrator, stats_dict):
    """
    Writes the saved stats dict into integrator global variables,
    so it can continue from the old run.  Keys must match variable names.
    """
    for key, val in stats_dict.items():
        try:
            integrator.setGlobalVariableByName(key, val)
        except Exception:
            print(f"Warning: integrator has no global var '{key}', skipping.")


def load_gamd_stats_from_file(integrator, filename):
    """
    Reads lines like 'key=value' from 'filename' and sets them in integrator.
    """
    if not os.path.exists(filename):
        print(f"Warning: GaMD stats file '{filename}' not found.")
        return
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or '=' not in line:
                continue
            key_str, val_str = line.split('=', 1)
            key_str = key_str.strip()
            val_str = val_str.strip()
            try:
                val = float(val_str)
            except ValueError:
                print(f"Warning: Could not parse float from '{val_str}'. Skipping.")
                continue
            try:
                integrator.setGlobalVariableByName(key_str, val)
            except Exception:
                print(f"Warning: integrator has no global var '{key_str}', skipping.")
