"""Test Case Handler.

Copyright (C)  Stichting Deltares, 2026
"""

import copy
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar, Dict, List, Tuple

from src.config.test_case_config import TestCaseConfig
from src.suite.program import Program
from src.utils.logging.i_logger import ILogger
from src.utils.paths import Paths


@dataclass
class DirectoryState:
    """Snapshot of a directory's state used to detect added/changed files.

    Attributes
    ----------
    files : Dict[str, datetime]
        Mapping of filename to last modification time (UTC).
    size : int
        Total size in bytes of all files in the directory at snapshot time.
    """

    files: Dict[str, datetime] = field(default_factory=dict)
    size: int = 0

    def __init__(self, files: Dict[str, datetime] | None = None, size: int = 0) -> None:
        self.files = files if files is not None else {}
        self.size = size


# Test case handler (compare or reference)
class TestCase:
    __test__: ClassVar[bool] = False

    # constructor
    # input: test case configuration
    def __init__(self, config: TestCaseConfig, logger: ILogger) -> None:
        self.__config = config
        self.__logger = logger
        self.__maxRunTime: float = self.__config.max_run_time
        self.__programs: List[Tuple[int, Program]] = []
        self.__errors: list[Exception] = []

        logger.debug(f"Initializing test case ({self.__config.name}), max runtime : {str(self.__maxRunTime)}")

        self.__config.run_file_name = os.path.join(self.__config.absolute_test_case_path, "_tb3_char.run")
        refrunfile = os.path.join(config.absolute_test_case_reference_path, "_tb3_char.run")

        if os.path.exists(refrunfile):
            refruntime = self.__findCharacteristicsRunTime__(refrunfile)
            if refruntime:
                self.__config.ref_run_time = refruntime
                if not self.__config.overrule_ref_max_run_time:
                    # set maxRunTime to 1.5 * reference runtime and add a few seconds (some systems start slow)
                    # The variation in runtimes vary a lot (different machines, other processes)
                    self.__maxRunTime = refruntime * 1.5 + 10.0
                    logger.info(f"Overwriting max run time via reference _tb3_char.run ({str(self.__maxRunTime)})")

        self.__maxRunTime = max(self.__maxRunTime, 120.0) * 5.0 + 300.0
        logger.debug(f"maxRunTime increased to {str(self.__maxRunTime)}")

    def run(self, programs: List[Program]) -> None:
        """Execute a Test Case.

        Execution does not throw errors, these can be retrieved from `getErrors`.

        Parameters
        ----------
        programs : List[Program]
            List of programs.

        Raises
        ------
        RuntimeError
            On time out.
        """
        # prepare the programs for running

        logger = self.__logger
        self.__initializeProgramList__(programs)

        logger.debug("Starting test case")

        # prepare presets for testbench run file
        pre_run_state = self.__get_state_directory(self.__config.absolute_test_case_path)
        pre_run_files = pre_run_state.files
        size = pre_run_state.size

        start_time = time.time()
        logger.debug(f"Test case start time {str(time.ctime(int(start_time)))}")

        # execute all programs, subprocess
        for program in self.__programs:
            program[1].run(logger)

            error = program[1].getError()
            return_code = program[1].last_return_code
            if not program[1].ignore_return_code and return_code != 0 and error is not None:
                self.__errors.append(error)

        # create testbench run file
        elapsed_time = time.time() - start_time
        self.__config.run_time = elapsed_time
        logger.debug(f"Test case elapsed time {str(elapsed_time)}")
        logger.debug("Creating _tb3_char.run for test case")

        with open(self.__config.run_file_name, "w") as runfile:
            runfile.write("Start_size:" + str(size) + "\n")
            runfile.write("Runtime:" + str(elapsed_time) + "\n")
            post_run_state = self.__get_state_directory(self.__config.absolute_test_case_path)
            for post_file in post_run_state.files:
                # collect all added and changed files in the working directory (after running, compare to initial list)
                if post_file not in {}.fromkeys(pre_run_files, 0):
                    runfile.write("Output_added:" + str(post_file) + "\n")
                    size = size + os.path.getsize(os.path.join(self.__config.absolute_test_case_path, post_file))
                else:
                    ftime = post_run_state.files[post_file]
                    if ftime != pre_run_files[post_file]:
                        runfile.write("Output_changed:" + str(post_file) + "\n")
            runfile.write("End_size:" + str(size) + "\n")

    def __get_state_directory(self, directory: str) -> DirectoryState:
        files: Dict[str, datetime] = {}
        size: int = 0

        # collect all initial files in the working directory before running
        for infile in os.listdir(directory):
            files[infile] = datetime.fromtimestamp(
                os.path.getmtime(os.path.join(directory, infile)),
                tz=timezone.utc,
            )
            size = size + os.path.getsize(os.path.join(directory, infile))

        return DirectoryState(files=files, size=size)

    # get errors from Test Case
    # output: list of Errors (type), can be None
    def getErrors(self):
        return self.__errors

    def __initializeProgramList__(self, programs: List[Program]):
        """Prepare programs from configuration."""
        # programs are loaded by the manager
        shell_arguments = " ".join(self.__config.shell_arguments)
        shell = self.__config.shell

        for program_config in self.__config.program_configs:
            # get the copy of the original program
            program: Program = next(p for p in programs if p.name == program_config.name)
            program_copy: Program = copy.deepcopy(program)

            # Combine the program workdir with the testcase workdir
            if program_config.working_directory:
                program_config.working_directory = Paths().mergePathElements(
                    self.__config.absolute_test_case_path,
                    program_config.working_directory,
                )
            else:
                program_config.working_directory = self.__config.absolute_test_case_path

            # overwrite run configuration with given overrides
            program_config.shell_arguments = shell_arguments
            program_config.shell = shell
            program_config.case_name = self.__config.name
            program_copy.overwriteConfiguration(program_config)

            # add runner sequence number and runner configuration to local storage
            self.__programs.append((program_config.sequence, program_copy))

    # retrieve runtime or none from _tb3_char.run file
    # input: path to _tb3_char.run file
    # output: actual runtime value (float)
    def __findCharacteristicsRunTime__(self, filename):
        with open(filename) as f:
            retval = None
            for line in f:
                if "Runtime:" in line:
                    _, value = line.split(":")
                    retval = float(value)
                    break
            return retval
