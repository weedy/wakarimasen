#!/usr/bin/python2

import os
import sys
import traceback

import fcgi
import werkzeug

import config, config_defaults
import app
import cli
import util
import model
import interboard
from board import Board, NoBoard
from util import WakaError, local

@util.headers
def application(environ, start_response):
    '''Main routing application'''

    local.environ = environ
    request = werkzeug.BaseRequest(environ)

    task = request.values.get('task', request.values.get('action', ''))
    boardname = request.values.get('board', 'sugg')


    environ['waka.task'] = task
    environ['waka.boardname'] = boardname
    # Indicate "pop-up window" UI style.
    environ['waka.fromwindow'] = False
    environ['waka.rootpath'] = os.path.join('/', config.BOARD_DIR, '')

    if not task and not boardname:
        environ['waka.board'] = NoBoard()
        return app.check_setup(environ, start_response)

    environ['waka.board'] = NoBoard()
    try:
        if boardname:
            environ['waka.board'] = Board(boardname)
        elif task not in ('entersetup', 'setup', 'loginpanel'):
            raise WakaError("No board parameter set")
        elif task == 'loginpanel':
            raise WakaError("No board parameter set. "
                "If you haven't created boards yet, do it now.")
    except WakaError, e:
        return app.error(environ, start_response, e)

    # the task function if it exists, otherwise no_task()
    function = getattr(app, 'task_%s' % task.lower(), app.no_task)

    try:
        interboard.remove_old_bans()
        interboard.remove_old_backups()
    except model.OperationalError, e:
        return ["Error initializing database: %s" % e.args[0]]

    try:
        # wrap with list() to run inside this try..except
        return list(function(environ, start_response))
    except WakaError, e:
        return app.error(environ, start_response, e)
    except:
        environ['waka.status'] = '503 Service unavailable'
        traceback.print_exc()
        return app.error(environ, start_response)


def cleanup(*args, **kwargs):
    '''Destroy the thread-local session and environ'''
    session = model.Session()
    session.commit()
    session.transaction = None  # fix for a circular reference
    model.Session.remove()
    local.environ = {}

application = util.cleanup(application, cleanup)

def main():
    try:
        app.init_database()
    except model.OperationalError, e:
        # CGI-friendly error message
        print "Content-Type: text/plain\n"
        print "Error initializing database: %s" % e.args[0]
        return

    if not sys.argv[1:] or sys.argv[1] == 'fcgi':
        fcgi.WSGIServer(application).run()
    else:
        cli.handle_command(sys.argv[1:], application)
        cleanup()

if __name__ == '__main__':
    main()
