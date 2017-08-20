import os
import subprocess
import time
import datetime
from notebook._tz import utcnow
from threading import Thread
from nbcull.culler import Culler, logger
from jupyter_core.paths import jupyter_runtime_dir


class TestCuller(object):

    BUFFER_TIME = 0.8     # in seconds
    TICK_TIME = 2       # in seconds
    STARTUP_TIMEOUT = 5   # in seconds
    NUM_OF_LOOPS = 3
    TEST_FILE_NAME = "test-file.txt"
    TEST_CONFIG_FILE_NAME = "nbperiodicrunner_config.py"
    TEST_CONFIG_FILE_CONTENTS = """
c.Culler.periodic_time_interval = 1
c.Culler.allowed_inactive_time = 5"""

    _condition = None
    _thread = None
    _notebook_process = None

    def setUp(self):
        Culler.CONFIG_FILE_PATH = "./"
        Culler.CONFIG_FILE_NAMES = [self.TEST_CONFIG_FILE_NAME]
        self._allowed_inactive_time = 5
        self._create_test_config_file()
        self._culler = Culler()
        self._culler.allowed_inactive_time = self._allowed_inactive_time

        if not os.path.exists(jupyter_runtime_dir()):
            os.mkdirs(jupyter_runtime_dir())

        self._remove_server_files()

        def condition():
            return os.path.exists(self.TEST_FILE_NAME)

        self._condition = condition

    def tearDown(self):
        self._culler.stop()
        self._delete_test_file()
        self._delete_test_config_file()
        self._kill_notebook()

    def test_notebook_install(self):
        self.setUp()
        subprocess.check_call(['pip3', 'install', '--upgrade', '.'])
        subprocess.check_call(['jupyter', 'serverextension', 'enable', '--py', 'nbcull'])

    def test_init_config(self):
        self.setUp()
        self._delete_test_config_file()
        self._culler = Culler()
        assert self._culler.periodic_time_interval == 2
        assert self._culler.allowed_inactive_time == 6

        self._create_test_config_file()
        self._culler._init_config()
        assert self._culler.periodic_time_interval == 1
        assert self._culler.allowed_inactive_time == self._allowed_inactive_time
        self.tearDown()

    def test_constructor(self):
        self.setUp()
        assert self._culler.periodic_time_interval == 1
        assert self._culler.allowed_inactive_time == self._allowed_inactive_time
        assert self._culler._periodic_callback
        self.tearDown()

    def test_seonds_to_milliseconds(self):
        self.setUp()
        list_of_seconds = [1, 5, 20, 4, 6, 9, 3.8]
        list_of_milliseconds = []
        for sec in list_of_seconds:
            list_of_milliseconds.append(self._culler._seconds_to_milliseconds(sec))

        expected_list_of_milliseconds = [1000, 5000, 20000, 4000, 6000, 9000, 3800]
        assert set(list_of_milliseconds) == set(expected_list_of_milliseconds)
        self.tearDown()

    def test_init_periodic_callback(self):
        self.setUp()
        self._culler._periodic_callback = None
        self._culler._init_periodic_callback()
        assert self._culler._periodic_callback
        self.tearDown()

    def test_check_activity(self):
        self.setUp()

        class Response:
            body = None
        response = Response()
        response.body = '{{"last_activity": "{}"}}'.format(
                            utcnow().replace(tzinfo=None).strftime(
                                self._culler.ACTIVITY_DATE_FORMAT
                                )
                            )
        assert self._culler._check_activity(response) is True
        response.body = '{{"last_activity": "{}"}}'.format(
                                (
                                    utcnow() - datetime.timedelta(0, self._culler.allowed_inactive_time)
                                ).replace(tzinfo=None).strftime(
                                    self._culler.ACTIVITY_DATE_FORMAT
                                )
                            )
        assert self._culler._check_activity(response) is False
        self.tearDown()

    def test_update_activity_flag(self):
        self.setUp()
        self._make_generic_notebook()
        self._culler._is_updating_flag = True
        assert self._culler._update_activity_flag() is False
        self._culler._is_updating_flag = False
        self._culler._server = self._culler._get_current_running_server()
        assert self._culler._update_activity_flag() is True
        self.tearDown()

    def test_get_current_running_server(self):
        self.setUp()
        self._make_generic_notebook()
        assert self._culler._get_current_running_server()['hostname'] == "localhost"
        self._kill_notebook()
        assert self._culler._get_current_running_server() is None
        self.tearDown()

    def test_find_api_status_endpoint(self):
        self.setUp()
        self._make_generic_notebook()
        result = self._culler._find_api_status_endpoint()
        assert result == "http://localhost:8888/api/status" and self._culler._server is not None
        self._kill_notebook()
        result = self._culler._find_api_status_endpoint()
        assert result is None and self._culler._server is None
        self.tearDown()

    def _remove_server_files(self):
        dir_name = jupyter_runtime_dir()
        for file in os.listdir(dir_name):
            if file.startswith('nbserver-'):
                os.remove(os.path.join(dir_name, file))

    def _is_within_buffer_time(self, duration):
        return abs(duration - self._culler.periodic_time_interval) < self.BUFFER_TIME

    def _is_timing_out(self, start_time):
        return time.time() - start_time > self._culler.periodic_time_interval + self.BUFFER_TIME

    def _delete_test_file(self):
        if os.path.exists(self.TEST_FILE_NAME):
            subprocess.check_call(['rm', self.TEST_FILE_NAME])

    def _delete_test_config_file(self):
        if os.path.exists(self.TEST_CONFIG_FILE_NAME):
            subprocess.check_call(['rm', self.TEST_CONFIG_FILE_NAME])

    def _create_test_config_file(self):
        with open(self.TEST_CONFIG_FILE_NAME, 'w') as config_file:
            config_file.write(self.TEST_CONFIG_FILE_CONTENTS)

    def _start_thread(self, command):
        self._thread = Thread(target=command)
        self._thread.daemon = True
        self._thread.start()

    def _make_generic_notebook(self):
        self._notebook_process = subprocess.Popen([
            'jupyter-notebook',
            '--debug',
            '--no-browser'])
        # Sleep so that notebook has enough time to make 'nbserver-*' file
        time.sleep(2)

    def _kill_notebook(self):
        if self._notebook_process:
            subprocess.check_call(['kill', '-9', str(self._notebook_process.pid)])
        else:
            logger.info("No process is set")
        self._remove_server_files()

    def _command_runs_on_time(self, num, command, condition, clean_up):
        self._start_thread(command)
        self._wait_until_startup_done(condition)

        for _ in range(num):
            clean_up()
            duration = self._get_time_to_meet_condition(condition)
            logger.info("The loop took {} seconds to run.".format(duration))
            assert self._is_within_buffer_time(duration)

    def _get_time_to_meet_condition(self, condition):
        start_time = time.time()

        # Set the default end_time to be a timeout, so fails test if times out.
        end_time = start_time + self._get_timeout_time()

        # check if file is created with `touch` cli in interval time
        while not self._is_timing_out(start_time):
            time.sleep(self.TICK_TIME)
            if condition():
                end_time = time.time()
                break

        return end_time - start_time

    def _wait_until_startup_done(self, condition):
        logger.info("Waiting for startup...")
        total_startup_duration = 0
        duration = self._get_timeout_time()

        while duration >= self._get_timeout_time() and total_startup_duration < self.STARTUP_TIMEOUT:
            duration = self._get_time_to_meet_condition(condition)
            total_startup_duration += duration
        logger.info("Startup took {} seconds".format(total_startup_duration))

    def _get_timeout_time(self):
        return self._culler.periodic_time_interval + self.BUFFER_TIME + 1
