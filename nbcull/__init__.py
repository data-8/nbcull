from nbcull.culler import Culler


def _jupyter_server_extension_paths():
    return [{
        'module': 'nbcull',
    }]


def load_jupyter_server_extension(nbapp):
    culler = Culler(nbapp.config)
    culler.start()
