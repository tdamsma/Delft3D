import os
from typing import List, Optional

from pyfakefs.fake_filesystem import FakeFilesystem
from pytest_mock import MockerFixture

from src.config.program_config import ProgramConfig
from src.config.test_case_config import TestCaseConfig
from src.suite.program import Program
from src.suite.test_bench_settings import TestBenchSettings
from src.suite.test_case import TestCase
from src.utils.logging.file_logger import FileLogger


class TestTestCase:
    def test_run__tb3_char_output_file(self, mocker: MockerFixture, fs: FakeFilesystem) -> None:
        # Arrange
        platform = "win64" if os.name == "nt" else "lnx64"
        logger = mocker.Mock(spec=FileLogger)
        config = self.create_test_case_config("name_1", platform=platform)
        fs.create_file(f"{config.absolute_test_case_path}/input1.input", contents="input data")
        test_case = TestCase(config, logger)

        mocked_program = mocker.Mock(spec=Program)
        mocked_program.run.side_effect = self.create_file_side_effect(f"{config.absolute_test_case_path}/out1.out")
        mocked_program.name.return_value = "program_1"
        test_case._TestCase__programs = [[0, mocked_program]]
        mocker.patch("src.suite.test_case.TestCase.__initializeProgramList__")

        # Act
        test_case.run([])

        # Assert
        assert fs.exists(f"{config.absolute_test_case_path}/_tb3_char.run"), "during run no _tb3_char.run was created"
        assert fs.exists(f"{config.absolute_test_case_path}/out1.out"), "program.run wasn't called correctly(no output)"
        with open(f"{config.absolute_test_case_path}/_tb3_char.run", "r") as file:
            lines = file.readlines()
            references = self.tb3_char_output()
            for line, reference in zip(lines, references):
                if line.startswith("Runtime:"):
                    assert reference.startswith("Runtime:"), "_tb3_char.run content does not match"
                else:
                    assert line == reference, "_tb3_char.run content does not match"

    def test_run__changes_runfile(self, mocker: MockerFixture, fs: FakeFilesystem) -> None:
        # Arrange
        logger = mocker.Mock(spec=FileLogger)
        config = self.create_test_case_config("name_2")
        fs.create_dir(config.absolute_test_case_path)
        input_path = f"{config.absolute_test_case_path}/input.mdu"
        fs.create_file(input_path, contents="input data")
        program_config = ProgramConfig()
        program_config.name = "program_1"
        program_config.path = "program_1"
        program_config.absolute_bin_path = "/bin/program_1"
        program_config.sequence = 0
        config.program_configs = [program_config]
        program = Program(program_config, TestBenchSettings())
        test_case = TestCase(config, logger)

        def run_side_effect(self, _logger) -> None:
            # Modify existing file.
            with open(input_path, "w") as file:
                file.write("updated input")
            # Add new file.
            with open(f"{config.absolute_test_case_path}/new.out", "w") as file:
                file.write("new output")
            self._Program__last_return_code = 0
            self._Program__error = None

        mocker.patch("src.suite.program.Program.run", new=run_side_effect)

        # Act
        test_case.run([program])

        # Assert
        run_file = f"{config.absolute_test_case_path}/_tb3_char.run"
        assert fs.exists(run_file)
        with open(run_file, "r") as file:
            lines = [line.strip() for line in file.readlines()]
        assert any(line == "Output_changed:input.mdu" for line in lines)
        assert any(line == "Output_added:new.out" for line in lines)

    def create_test_case_config(self, name: str, platform: Optional[str] = "lnx64") -> TestCaseConfig:
        config = TestCaseConfig()
        config.name = name
        config.max_run_time = 100.0
        config.absolute_test_case_path = f"/case/{name}"
        config.absolute_test_case_reference_path = f"/reference/{platform}/{name}"

        return config

    def create_file_side_effect(self, filename):
        def side_effect(*args, **kwargs) -> None:
            with open(filename, "w") as f:
                f.write("File content")
            return None  # Return None to mimic the function call

        return side_effect

    def tb3_char_output(self) -> List[str]:
        return [
            "Start_size:10\n",
            "Runtime:0.004995584487915039\n",
            "Output_added:out1.out\n",
            "Output_added:_tb3_char.run\n",
            "End_size:22\n",
        ]
