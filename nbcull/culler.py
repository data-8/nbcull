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
    ACTIVITY_DATE_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'

    periodic_time_interval = Float(2, config=True, help="""
        Interval in seconds at which Culler checks if user is active.
    """)

    allowed_inactive_time = Float(6, config=True, help="""
        Time until the extension shuts the notebook down due to inactivity.
    """)

    def __init__(self, nbapp=None):
        self._nbapp = nbapp
        self._init_config()
        self._init_periodic_callback()
        self._server = None
        self._url = None
        self._is_user_active = True
        self._is_updating_flag = False

    def _init_config(self):
        c = Config()
        if self._nbapp:
            c.merge(self._nbapp.config)
        nbcull_config = load_pyconfig_files(self.CONFIG_FILE_NAMES, self.CONFIG_FILE_PATH)
        c.merge(nbcull_config)
        self.update_config(c)

    def _find_api_status_endpoint(self):
        self._server = self._get_current_running_server()
        if self._server is not None:
            return url_path_join(
                self._server['url'],
                self._server['base_url'],
                '/api/status'
            )
            logger.info("Status API endpoint: {}".format(self._url))
        else:
            return None

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

    def _update_activity_flag(self):
        if self._is_updating_flag:
            return False
        else:
            self._is_updating_flag = True

        def _command_wrapper(response):
            self._is_user_active = self._check_activity(response)

        AsyncHTTPClient().fetch(
            self._url,
            _command_wrapper,
            headers={
                'Authorization': 'Token {}'.format(self._server['token'])
            }
        )
        return True

    def _check_activity(self, response):
        last_activity = datetime.strptime(
            json.loads(response.body)['last_activity'],
            self.ACTIVITY_DATE_FORMAT
        )
        current_time = utcnow().replace(tzinfo=None)
        seconds_since_last_activity = (current_time - last_activity).total_seconds()
        logger.info("User has been inactive for {} seconds.".format(seconds_since_last_activity))
        self._is_updating_flag = False
        return seconds_since_last_activity < self.allowed_inactive_time

    def _get_current_running_server(self):
        try:
            return next(list_running_servers())
        except StopIteration:
            logger.info("There are no running servers")
            return None

    def _shut_down_notebook(self):
        self.stop()
        self._nbapp.stop()
        logger.info("Shutting down notebook because user has been \
inactive for at least {} seconds.".format(self.allowed_inactive_time))

    def _init_periodic_callback(self):
        def _command_wrapper():
            if self._url is not None:
                if self._update_activity_flag() and not self._is_user_active:
                    self._shut_down_notebook()
            else:
                self._url = self._find_api_status_endpoint()

        time_interval = self._seconds_to_milliseconds(self.periodic_time_interval)

        self._periodic_callback = PeriodicCallback(_command_wrapper, time_interval)
        logger.info('Initialized periodic callback on IOLoop: {}'.format(str(IOLoop.current())))

    def _seconds_to_milliseconds(self, seconds):
        return seconds * 1000
