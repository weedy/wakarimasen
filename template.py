import os
import sys
import glob
import jinja2

import config, config_defaults
import strings_en as strings

TEMPLATES_DIR = 'templates'
CACHE_DIR = os.path.join(TEMPLATES_DIR, '.cache')

_filters = []
_functions = []

def filter(f):
    _filters.append(f.__name__)
    return f

def function(f):
    _functions.append(f.__name__)
    return f

class Template(object):
    def __init__(self, name, **vars):
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)

        # Environment init
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
            bytecode_cache=jinja2.FileSystemBytecodeCache(CACHE_DIR)
        )
        
        for filter in _filters:
            self.env.filters[filter] = getattr(self, filter)
        
        for function in _functions:
            self.env.globals[function] = getattr(self, function)

        # Current template init
        self.template = self.env.get_template(name + '.html')

        self.board = vars.get('board', None)
        self.environ = vars.get('environ', {})

        if not self.board and self.environ:
            self.board = self.environ['waka.board']
            vars['board'] = self.board

        vars['stylesheets'] = list(self.get_stylesheets())
        self.env.globals['config'] = config
        self.env.globals['strings'] = strings

        self.vars = vars

    def __iter__(self):
        yield self.template.render(**self.vars).encode("utf-8")

    @filter
    def reverse_format(self, value, tplstring):
        return tplstring % value

    @filter
    def expand_url(self, filename, force_http=False):
        return self.board.expand_url(filename, force_http, self.environ)

    @filter
    def root_path_to_filename(self, filename):
        if filename.startswith("/") or filename.startswith("http"):
            return filename

        self_path = '/' # TODO

        return self_path + filename

    @function
    def get_script_name(self):
	return self.environ['SCRIPT_NAME']

    @function
    def get_secure_script_name(self):
        if config.USE_SECURE_ADMIN:
            return 'https://' + self.environ['SERVER_NAME'] + self.environ['SCRIPT_NAME']
	return self.environ['SCRIPT_NAME']

    def get_stylesheets(self):
        # FIXME: don't hardcode the path
        for file in glob.glob("include/common/css/*.css"):
            title = os.path.basename(file) \
                .replace(".css", "") \
                .replace("_", " ").title()

            if title == self.board.options['DEFAULT_STYLE']:
                default = 1
            else:
                default = 0

            yield {
                'filename': '/' + file,
                'title': title,
                'default': default,
            }
