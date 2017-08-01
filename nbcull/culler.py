import logging
from tornado.ioloop import PeriodicCallback, IOLoop
from traitlets.config.configurable import Configurable, Config
from traitlets import Float
from traitlets.config.loader import load_pyconfig_files


logging.basicConfig(
    format='[%(asctime)s] %(levelname)s -- %(message)s',
    level=logging.DEBUG)
logger = logging.getLogger('app')


class Culler(Configurable):

    CONFIG_FILE_PATH = '~/.jupyter'
    CONFIG_FILE_NAMES = ['nbculler_config.py']

    periodic_time_interval = Float(2, config=True, help="""
        Interval in seconds at which Culler checks if user is active.
    """)

    allowed_inactive_time = Float(6, config=True, help="""
        Time until the extension shuts the notebook down due to inactivity.
    """)

    def __init__(self, nbapp_config=None):
        self._init_config(nbapp_config)
        self._init_periodic_callback()
        self._time_inactive = 0

    def _init_config(self, nbapp_config=None):
        c = Config()
        if nbapp_config:
            c.merge(nbapp_config)
        nbcull_config = load_pyconfig_files(self.CONFIG_FILE_NAMES, self.CONFIG_FILE_PATH)
        c.merge(nbcull_config)
        self.update_config(c)

    def start(self):
        if self._periodic_callback:
            self._periodic_callback.start()
            IOLoop.current().start()
            logger.info('Started runner loop')
        else:
            logger.info('Did not start loop: No periodic callback exists.')

    def stop(self):
        if self._periodic_callback:
            self._periodic_callback.stop()
            logger.info('Stopped runner loop')
        else:
            logger.info('Did not stop loop: No periodic callback exists.')

    def is_running(self):
        return self._periodic_callback and self._periodic_callback.is_running()

    def _user_is_active(self):
        return False

    def _shut_down_notebook(self):
        logger.info("Shutting down notebook...")

    def _should_shutdown(self):
        return self._time_inactive >= self.allowed_inactive_time

    def _init_periodic_callback(self):
        def _command_wrapper():
            if not self._user_is_active():
                self._time_inactive += self.periodic_time_interval
                if self._should_shutdown():
                    self._shut_down_notebook()
                logger.info("User is not active. Total time inactive: {} sec".format(self._time_inactive))
            else:
                self._time_inactive = 0
                logger.info("User is active")

        time_interval = self._seconds_to_milliseconds(self.periodic_time_interval)

        self._periodic_callback = PeriodicCallback(_command_wrapper, time_interval)
        logger.info('Initialized periodic callback on IOLoop: {}'.format(str(IOLoop.current())))

    def _seconds_to_milliseconds(self, seconds):
        return seconds * 1000
