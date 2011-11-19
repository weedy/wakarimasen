'''Operations that affect multiple boards or the entire site,
e.g., transferring and merging threads.'''

import time
import re
import os
from urllib import urlencode

import config
import strings
import board
import staff
import model
import util
import str_format
import misc
from template import Template
from util import WakaError, local

from sqlalchemy.sql import case, or_, and_, select, func, null

# Common Site Table!

def get_all_boards(check_board_name=''):
    '''Get all the board names. All of them.'''

    session = model.Session()
    table = model.common
    sql = select([table.c.board]).order_by(table.c.board)

    query = session.execute(sql)

    board_present = False
    boards = []
    for row in query:
        boards.append({'board_entry' : row['board']})
        if row['board'] == check_board_name:
            board_present = True

    if check_board_name and not board_present:
        add_board_to_index(check_board_name)
        boards.append({'board_entry' : check_board_name})

    return boards

def add_board_to_index(board_name):
    session = model.Session()
    table = model.common
    sql = table.insert().values(board=board_name, type='')

    session.execute(sql)

def remove_board_from_index(board_name):
    session = model.Session()
    table = model.common
    sql = table.delete().where(table.c.board == board_name)

    session.execute(sql)

# Bans and Whitelists

def add_admin_entry(admin, option, comment, ip='', mask='255.255.255.255',
                    sval1='', total='', expiration=0, caller=''):
    staff.check_password(admin)

    session = model.Session()
    table = model.admin

    ival1 = ival2 = 0

    if not comment:
        raise WakaError(strings.COMMENT_A_MUST)
    if option in ('ipban', 'whitelist'):
        if not ip:
            raise WakaError('IP address required.')
        if not mask:
            mask = '255.255.255.255'
        # Convert to decimal.
        (ival1, ival2) = (misc.dot_to_dec(ip), misc.dot_to_dec(mask))
        sql = table.select().where(table.c.type == option)
        query = session.execute(sql)

        for row in query:
            if row.ival1 & row.ival2 == ival1 & ival2:
                raise WakaError('IP address and mask match ban #%d.' % \
                                (row.num))
    else:
        if not sval1:
            raise WakaError(STRINGFIELDMISSING)
        sql = table.select().where(and_(table.c.sval1 == sval1,
                                        table.c.type == option))
        row = session.execute(sql).fetchone()

        if row:
            raise WakaError('Duplicate String in ban #%d.' % (row.num))

    comment = str_format.clean_string(\
        str_format.decode_string(comment, config.CHARSET))
    expiration = int(expiration)
    if expiration:
        expiration = expiration + time.time()

    sql = table.insert().values(type=option, comment=comment, ival1=ival1,
                                ival2=ival2, sval1=sval1, total=total,
                                expiration=expiration)
    session.execute(sql)

    if total:
        add_htaccess_entry(ip)

    # TODO: Log this.

    forward_url = '?'.join((misc.get_secure_script_name(),
                            urlencode({'task' : 'bans'})))

    return util.make_http_forward(forward_url, config.ALTERNATE_REDIRECT)

def remove_admin_entry(admin, num, override_log=False, no_redirect=False):
    staff.check_password(admin)

    session = model.Session()
    table = model.admin
    sql = table.select().where(table.c.num == num)
    row = session.execute(sql).fetchone()

    if row:
        if row['total']:
            ip = misc.dec_to_dot(row['ival'])
            remove_htaccess_entry(ip)

        sql = table.delete().where(table.c.num == num)
        session.execute(sql)

    return util.make_http_forward('%s?task=bans' % \
                                  (misc.get_secure_script_name()))

def remove_old_bans():
    session = model.Session()
    table = model.admin
    sql = select([table.c.ival1, table.c.total],
                 and_(table.c.expiration <= time.time(),
                      table.c.expiration != 0))
    query = session.execute(sql)

    for row in query:
        sql = table.delete().where(table.c.ival1 == row['ival1'])
        session.execute(sql)
        if row['total']:
            ip = misc.dec_to_dot(row['ival1'])
            remove_htaccess_entry(misc.dec_to_dot(ip))

def add_htaccess_entry(ip):
    pass

def remove_htaccess_entry(ip):
    pass

def ban_check(numip, name, subject, comment):
    '''This function raises an exception if the IP address is banned, or
    the post contains a forbidden (non-spam) string. It otherwise returns
    nothing.'''

    session = model.Session()
    table = model.admin

    # IP Banned?
    sql = table.select().where(and_(table.c.type == 'ipban',
                                    table.c.ival1.op('&')(table.c.ival2) \
                                        == table.c.ival2.op('&')(numip)))
    ip_row = session.execute(sql).fetchone()

    if ip_row:
        raise WakaError('Address %s banned. Reason: %s' % \
            (misc.dec_to_dot(numip), ip_row.comment))
    
    # To determine possible string bans, first normalize input to lowercase.
    comment = comment.lower()
    subject = subject.lower()
    name = name.lower()

    sql = select([table.c.sval1], table.c.type == 'wordban')
    query = session.execute(sql)

    for row in query:
        bad_string = row.sval1.lower()
        if comment.count(bad_string) or subject.count(bad_string) or \
            name.count(bad_string):
            raise WakaError(strings.STRREF)

def mark_resolved(admin, delete, posts):
    user = staff.check_password(admin)

    referer = local.environ['HTTP_REFERER']

    errors = []
    board_obj = None
    for (board_name, posts) in posts.iteritems():
        # Access rights enforcement.
        if user.account == staff.MODERATOR and board_name not in user.reign:
            errors.append({'error' : '/%s/*: Sorry, you lack access rights.'\
                                     % (board_name)})
            continue

        for post in posts:
            session = model.Session()
            table = model.report
            sql = table.select().where(and_(table.c.postnum == post,
                                            table.c.board == board_name))
            row = session.execute(sql).fetchone()
            if not row:
                errors.append({'error' : '%s,%d: Report not found.'\
                                         % (board_name, int(post))})
                continue

            sql = table.delete().where(and_(table.c.postnum == post,
                                            table.c.board == board_name))
            session.execute(sql)

        if delete:
            try:
                board_obj = board.Board(board_name)
            except WakaError:
                errors.append({'error' : '%s,*: Error loading board.'\
                                         % (board_name)})
                continue
            try:
                board_obj.delete_stuff(posts, '', False, False, admin=admin)
            except WakaError:
                errors.append({'error' : '%s,%d: Post already deleted.'\
                                         % (board_name, int(post))})

    # TODO: Staff logging

    # TODO: This probably should be refactored into StaffInterface.
    return Template('report_resolved', errors=errors,
                                       error_occurred=len(errors)>0,
                                       admin=admin,
                                       username=user.username,
                                       type=user.account,
                                       boards_select=user.reign,
                                       referer=referer)


# TODO: Implement edit_admin_entry().

def trim_reported_posts(date=0):
    mintime = 0
    if date:
        mintime = time.time() - date
    elif config.REPORT_RETENTION:
        mintime = time.time() - config.REPORT_RETENTION

    if mintime > 0:
        session = model.Session()
        table = model.report
        sql = table.delete().where(table.c.timestamp <= mintime)
        session.execute(sql)

def update_spam_file(admin, spam):
    user = staff.check_password(admin)
    if user.account == staff.MODERATOR:
        raise WakaError(strings.INUSUFFICENTPRIVLEDGES)

    # Dump all contents to first spam file.
    with open(config.SPAM_FILES[0], 'w') as f:
        f.write(spam)

    forward_url = '?'.join([misc.get_secure_script_name(),
                            urlencode({'task' : 'spam'})])
    return util.make_http_forward(forward_url, config.ALTERNATE_REDIRECT)

# Thread Transfer

def move_thread(admin, parent, src_brd_obj, dest_brd_obj):
    if not parent:
        raise WakaError('No thread specified.')
    if src_brd_obj.name == dest_brd_obj.name:
        raise WakaError('Source and destination boards match.')

    # Check administrative access rights to both boards.
    src_brd_obj.check_access(admin)
    dest_brd_obj.check_access(admin)

    session = model.Session()
    src_table = src_brd_obj.table
    dest_table = dest_brd_obj.table

    sql = select([src_table.c.parent], src_table.c.num == parent)
    row = session.execute(sql).fetchone()

    if not row:
        raise WakaError('Thread not found.')
    elif row[0]:
        # Automatically correct if reply instead of thread was given.
        parent = row[0]

    sql = src_table.select().where(or_(src_table.c.num == parent,
                                       src_table.c.parent == parent))\
                            .order_by(src_table.c.num.asc())
    thread = [dict(x.items()) for x in session.execute(sql).fetchall()]

    # Indicate OP post number after insertion.
    new_parent = 0

    # List of images/thumbs to move around.
    image_move = []
    thumb_move = []

    lasthit = time.time()

    # DB operations
    for post in thread:
        # Grab post contents as dictionary of updates. Remove primary key.
        del post['num']

        post['lasthit'] = lasthit
        image = post['image']
        thumbnail = post['thumbnail']

        if image:
            image_move.append(image)
        if thumbnail \
            and re.match(src_brd_obj.options['THUMB_DIR'], thumbnail):
            thumb_move.append(thumbnail)

        # Update post reference links.
        if new_parent:
            post['parent'] = new_parent

            new_comment = re.sub(r'a href="(.*?)'
                + os.path.join(src_brd_obj.path,
                               src_brd_obj.options['RES_DIR'],
                               '%d%s' % (int(parent)), config.PAGE_EXT),
                r'a href="\1' + os.path.join(\
                               dest_brd_obj.path,
                               dest_brd_obj.options['RES_DIR'],
                               '%d%s' % (int((new_parent), config.PAGE_EXT)),
                post['comment']))

            post['comment'] = new_comment

        sql = dest_table.insert().values(**post)
        result = session.execute(sql)

        if not new_parent:
            new_parent = result.last_inserted_ids()[0]

    # Nested associate for moving files in bulk.
    def rename_files(filename_list, dir_type):
        for filename in filename_list:
            src_filename = os.path.join(src_brd_obj.path, filename)
            dest_filename = re.sub('^/?' + src_brd_obj.options[dir_type],
                                   dest_brd_obj.options[dir_type],
                                   filename)
            dest_filename = os.path.join(dest_brd_obj.path, dest_filename)
            os.rename(src_filename, dest_filename)

    # File transfer operations.
    rename_files(image_move, 'IMG_DIR')
    rename_files(thumb_move, 'THUMB_DIR')

    dest_brd_obj.build_cache()
    dest_brd_obj.build_thread_cache(new_parent)

    src_brd_obj.delete_stuff([parent], '', False, False, caller='internal')

    forward_url = '?'.join((misc.get_secure_script_name(),
                            urlencode({'task' : 'mpanel',
                                       'board' : dest_brd_obj.name,
                                       'page' : 't' + str(new_parent)})))

    return util.make_http_forward(forward_url)

# Advanced Administration
