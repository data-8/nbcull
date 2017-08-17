import logging
import json
from notebook.notebookapp import list_running_servers
from notebook._tz import utcnow
from datetime import datetime
from tornado.httpclient import AsyncHTTPClient
from notebook.utils import url_path_join
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

    def __init__(self, nbapp=None):
        self._nbapp = nbapp
        if nbapp:
            self._init_config(nbapp.config)
        else:
            self._init_config()
        self._init_periodic_callback()
        self._server = None
        self._is_user_active = True
        self._url = None
        self._is_updating_flag = False

    def _init_config(self, nbapp_config=None):
        c = Config()
        if nbapp_config:
            c.merge(nbapp_config)
        nbcull_config = load_pyconfig_files(self.CONFIG_FILE_NAMES, self.CONFIG_FILE_PATH)
        c.merge(nbcull_config)
        self.update_config(c)

    def _init_url(self):
        self._server = self._get_current_running_server()
        if self._server is not None:
            self._url = url_path_join(
                self._server['url'],
                self._server['base_url'],
                '/api/status'
            )
            logger.info("URL: {}".format(self._url))

    def start(self):
        if self._periodic_callback:
            self._periodic_callback.start()
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

    def _check_activity(self):
        if self._is_user_active:
            logger.info("User is still active...")
        else:
            self._shut_down_notebook()

    def _update_activity_flag(self):
        if self._is_updating_flag:
            return
        else:
            self._is_updating_flag = True

        def _command_wrapper(response):
            logger.info("Checking if user is active...")
            last_activity = datetime.strptime(
                json.loads(response.body)['last_activity'],
                '%Y-%m-%dT%H:%M:%S.%fZ'
            )
            current_time = utcnow().replace(tzinfo=None)
            seconds_since_last_activity = (current_time - last_activity).total_seconds()
            logger.info("User has been inactive for {} seconds.".format(seconds_since_last_activity))
            self._is_user_active = seconds_since_last_activity < self.allowed_inactive_time
            self._is_updating_flag = False

        AsyncHTTPClient().fetch(
            self._url,
            _command_wrapper,
            headers={
                'Authorization': 'Token ' + self._server['token']
            }
        )

    def _get_current_running_server(self):
        try:
            return next(list_running_servers())
        except:
            logger.info("There are no running servers")
            return None

    def _shut_down_notebook(self):
        self._nbapp.stop()
        logger.info("Shutting down notebook...")

    def _init_periodic_callback(self):
        self._periodic_callback = None

        def _command_wrapper():
            if self._url is not None:
                self._update_activity_flag()
                self._check_activity()
            else:
                self._init_url()

        time_interval = self._seconds_to_milliseconds(self.periodic_time_interval)

        self._periodic_callback = PeriodicCallback(_command_wrapper, time_interval)
        logger.info('Initialized periodic callback on IOLoop: {}'.format(str(IOLoop.current())))

    def _seconds_to_milliseconds(self, seconds):
        return seconds * 1000
