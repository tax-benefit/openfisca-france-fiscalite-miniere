import sys

from openfisca_core.scripts import build_tax_benefit_system
# from openfisca_core.scripts.serve import read_user_configuration
from openfisca_core.scripts.openfisca_command import get_parser

from openfisca_web_api.app import create_app
from openfisca_web_api.scripts.serve import (
    OpenFiscaWebAPIApplication,
    DEFAULT_PORT,
    HOST,
    DEFAULT_WORKERS_NUMBER,
    DEFAULT_TIMEOUT
)

from flask import jsonify  # TODO catch ImportError


class FiscaliteMiniereWebAPI(OpenFiscaWebAPIApplication):
    def load(self):
        app = super().load()

        # @app.route('/matrices')
        def get_matrices():
            # TODO POST request + return zip
            return jsonify({
                'welcome': 'coucou'
                }), 200

        app.add_url_rule('/matrices', 'matrices', get_matrices)
        print(app.url_map)


def main(parser):
    configuration = {
        'port': DEFAULT_PORT,
        'bind': '{}:{}'.format(HOST, DEFAULT_PORT),
        'workers': DEFAULT_WORKERS_NUMBER,
        'timeout': DEFAULT_TIMEOUT,
        }
    # configuration = read_user_configuration(configuration, parser)
    FiscaliteMiniereWebAPI(configuration).run()



if __name__ == '__main__':
    sys.exit(main(get_parser()))
