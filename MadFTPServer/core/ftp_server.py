# -*- coding: utf-8 -*-

import os
import json
import ConfigParser
import hashlib
from conf import settings
from core.common import check_password, get_quotation
import shutil
import socket
import selectors2 as selectors

STANDARD_QUOTATION = 300L * 1024 * 1024
STATUS_CODE = {
    200: "Info",
    250: "Invalid cmd format",
    251: "Invalid cmd",
    252: "Invalid auth data",
    253: "Wrong username or password",
    254: "Passed authentication",
    255: "Filename doesn't provided",
    256: "File doesn't exist",
    257: "ready to send file",
    258: "md5 verification",
    259: "ready to receive file",
    260: "pwd message",
    261: "mkdir success",
    262: "dir already exists",
    263: "cd success",
    264: "dir not exists",
    265: "can not cd upper dir",
    266: "ls success",
    267: "rm success",
    268: "continue to receive file",
    269: "df success",
    270: "full quotation, you have no space to put file",
    271: "exit",
}


# FTP类
class FTPHandler(object):

    def __init__(self):
        self.selector = selectors.DefaultSelector()
        self.server = socket.socket()
        self.server.setblocking(False)
        # 存放文件路径
        self.file_path_dict = {}
        # 存放文件总大小
        self.file_size_dict = {}
        # 存放get文件对象
        self.get_fd_dict = {}
        # 存放put文件对象
        self.put_fd_dict = {}
        # 存放put收到文件大小
        self.put_file_size_dict = {}
        # 存放get发送文件大小
        self.get_file_size_dict = {}
        # 存放用户数据
        self.user_data = {}

    def start(self):
        self.server.bind((settings.HOST, settings.PORT))
        self.server.listen(5)
        self.selector.register(self.server, selectors.EVENT_READ, self.accept)

    def accept(self, server):
        conn, addr = server.accept()
        print("accepted from", addr)
        # 设置非阻塞
        conn.setblocking(False)
        # 注册事件，有新连接回调read函数
        self.selector.register(conn, selectors.EVENT_READ, self.write)

    def monitor(self):
        while 1:
            ready_list = self.selector.select()
            for key, event in ready_list:
                key.data(key.fileobj)

    def write(self, conn):
        self.selector.unregister(conn)
        self.selector.register(conn, selectors.EVENT_READ, self.read)

    # 连接实例调用的数据处理方法
    def read(self, conn):
        data = conn.recv(1024).strip()
        # 数据为空
        if not data:
            self.selector.unregister(conn)
            conn.close()
        # print(data)
        # 解析json数据
        # 先decode后loads
        data = json.loads(data.decode('utf-8'))
        action = data.get("action", None)
        # 构造函数名，避免关键字冲突
        # 反射不支持私有方法
        action_func = "_%s" % action
        if action:
            if hasattr(self, action_func):
                func = getattr(self, action_func)
                func(conn, **data)
            else:
                print("invalid cmd")
                self.send_response(conn, 251)
        else:
            print("invalid cmd format")
            self.send_response(conn, 250)

    def send_response(self, request, status_code, data=None):
        """
        统一处理返回客户端数据
        """
        response = {'status_code': status_code, 'status_msg': STATUS_CODE[status_code]}
        if data:
            # 更新数据,字典更新用update
            response.update(data)
        # 先dumps后encode
        print "send: ", response
        request.send(json.dumps(response).encode('utf-8'))

    def authenticate(self, username, token=None):
        """
        验证用户合法性，合法返回数据
        """
        config = ConfigParser.ConfigParser()
        config.read(settings.ACCOUNT_DIR)
        if username in config.sections():
            _password = config.get(username, 'Password')
            token = token.encode('utf-8')
            print "token: {}".format(token)
            if check_password(_password, token):
                return config.items(username)
            else:
                return
        else:
            return

    def _auth(self, conn, *args, **kwargs):
        username = kwargs.get('username', None)
        # password = kwargs.get('password', None)
        token = kwargs.get('token', None)
        if not username or not token:
            self.send_response(conn, 252)
        # 返回格式[('password', '123'), ('quotation', '100')]转换成字典
        userdata = self.authenticate(username, token)
        if userdata:
            userdata = dict(userdata)
            userdata.update(username=username)
            print("Pass Auth: ", userdata)
            user_home_dir = "%s/%s" % (settings.USER_HOME, userdata.get('username', ''))
            quotation = userdata.get('quotation')
            if quotation and str(quotation).isdigit():
                quotation = long(quotation) * 1024 * 1024
            else:
                print "Invalid or empty quotation, set standard quotation"
                quotation = STANDARD_QUOTATION
            userdata.update(user_home_dir=user_home_dir, quotation=quotation)
            self.user_data[conn] = userdata
            self.send_response(conn, 254)
        else:
            self.send_response(conn, 253)
        # self.selector.unregister(conn)
        # self.selector.register(conn, selectors.EVENT_READ, self.write)
        self.write(conn)

    def _put(self, conn, *args, **kwargs):
        """
        client send file to server
        :return:
        """
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        quotation = self.user_data[conn].get('quotation', '')
        filename = kwargs.get('filename', None)
        filesize = kwargs.get('filesize', 0)
        offset = kwargs.get('offset', '')
        dest_dir = user_home_dir
        if offset:
            dest_dir += '/' + offset
        file_abs_path = "%s/%s" % (dest_dir, filename)
        if (get_quotation(user_home_dir) + long(filesize)) > quotation:
            print "full quotation"
            self.send_response(conn, 270)
            return
        ret = os.path.isfile(file_abs_path)
        if not ret:
            print "ready to receive file--"
            self.send_response(conn, 259)
            received_size = 0
            file_obj = open(file_abs_path, 'wb')
        else:
            print "continue to receive file--"
            received_size = os.path.getsize(file_abs_path)
            self.send_response(conn, 268, data={'recvsize': received_size})
            file_obj = open(file_abs_path, 'ab')
        self.put_fd_dict[conn] = file_obj
        self.put_file_size_dict[conn] = received_size
        self.file_size_dict[conn] = filesize

        self.selector.unregister(conn)
        self.selector.register(conn, selectors.EVENT_READ, self.put)

    def put(self, conn):
        file_obj = self.put_fd_dict[conn]
        filesize = self.file_size_dict[conn]
        data = conn.recv(4096)
        file_obj.write(data)
        self.put_file_size_dict[conn] += len(data)

        if self.put_file_size_dict[conn] == filesize:
            print("----->file rece done-----")
            del self.put_file_size_dict[conn]
            del self.file_size_dict[conn]
            del self.put_fd_dict[conn]

            file_obj.close()
            self.write(conn)

    def _get(self,  conn, *args, **kwargs):
        """
        server send file to client
        :return:
        """
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        filename = kwargs.get('filename', None)
        received_size = kwargs.get("recvsize", None)
        dest_dir = user_home_dir
        # 如果是从当前目录取文件
        if not filename.startswith('/'):
            # 用户所在位置
            offset = kwargs.get('offset', '')
            if offset:
                dest_dir += '/' + offset
        file_abs_path = "%s/%s" % (dest_dir, filename)
        if os.path.isfile(file_abs_path):
            file_size = os.path.getsize(file_abs_path)
            self.send_response(conn, 257, data={'filesize': file_size})
            self.file_path_dict[conn] = file_abs_path
            self.get_file_size_dict[conn] = received_size
            self.file_size_dict[conn] = file_size

            self.selector.unregister(conn)
            self.selector.register(conn, selectors.EVENT_READ, self.get_clean)
        else:
            self.send_response(conn, 256)
            self.write(conn)

    def get_clean(self, conn):
        # 强制清空数据缓存，避免粘包问题
        conn.recv(1024)
        file_abs_path = self.file_path_dict[conn]
        file_obj = open(file_abs_path, "rb")
        received_size = self.get_file_size_dict[conn]
        if received_size:
            print "continue to send file--"
            file_obj.seek(received_size)
        else:
            print "ready to send file--"

        self.get_fd_dict[conn] = file_obj
        self.selector.unregister(conn)
        self.selector.register(conn, selectors.EVENT_WRITE, self.get)

        conn.send(file_obj.readline())

    def get(self, conn):
        file_obj = self.get_fd_dict[conn]
        conn.send(file_obj.readline())
        get_size = file_obj.tell()
        file_size = self.file_size_dict[conn]

        if get_size == file_size:
            del self.get_fd_dict[conn]
            del self.file_path_dict[conn]
            del self.file_size_dict[conn]
            del self.get_file_size_dict[conn]
            file_obj.close()
            self.write(conn)

    def _ls(self,  conn, *args, **kwargs):
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        offset = kwargs.get('offset', '')
        dest_dir = '/'.join([user_home_dir, offset])
        if os.path.isdir(dest_dir):
            data = ','.join(os.listdir(dest_dir))
            self.send_response(conn, 266, data={'ls': data})
        else:
            self.send_response(conn, 264)
        self.write(conn)

    def _cd(self,  conn, *args, **kwargs):
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        offset = kwargs.get('offset', '')
        filedir = kwargs.get('filedir', '')
        if not filedir.startswith('/'):
            dest_dir = '/'.join([user_home_dir, offset])
            filedir_list = filedir.split('/')
            for f in filedir_list:
                if f == '.':
                    dest_dir = dest_dir
                elif f == '..':
                    dest_dir = os.path.dirname(dest_dir)
                    # 已是用户根目录
                    if len(dest_dir) < len(user_home_dir):
                        self.send_response(conn, 265, data={'offset': offset})
                else:
                    dest_dir += '/' + f
            offset_now = dest_dir.split(user_home_dir)[-1].strip('/')
        else:
            dest_dir = '/'.join([user_home_dir, filedir])
            offset_now = filedir.strip('/')
        if os.path.exists(dest_dir):
            self.send_response(conn, 263, data={'offset': offset_now})
        else:
            self.send_response(conn, 264)
        self.write(conn)

    def _pwd(self,  conn, *args, **kwargs):
        offset = kwargs.get('offset', '')
        pwd = '/'
        if offset:
            pwd += offset.strip()
        data = {
            'pwd': pwd
        }
        self.send_response(conn, 260, data=data)
        self.write(conn)

    def _mkdir(self,  conn, *args, **kwargs):
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        offset = kwargs.get('offset', '')
        filedir = kwargs.get('filedir', '')
        if not filedir.startswith('/'):
            dir_list = [user_home_dir, offset, filedir]
            dest_dir = '/'.join(dir_list)
        else:
            dest_dir = user_home_dir.rstrip('/') + filedir
        if os.path.exists(dest_dir):
            self.send_response(conn, 262)
        else:
            os.makedirs(dest_dir)
            self.send_response(conn, 261)
        self.write(conn)

    def _rm(self,  conn, *args, **kwargs):
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        offset = kwargs.get('offset', '')
        filedir = kwargs.get('filedir', '')
        if not filedir.startswith('/'):
            dir_list = [user_home_dir, offset, filedir]
            dest_dir = '/'.join(dir_list)
        else:
            dest_dir = user_home_dir.rstrip('/') + filedir
        if not os.path.exists(dest_dir):
            self.send_response(conn, 264)
        else:
            if os.path.isdir(dest_dir):
                shutil.rmtree(dest_dir)
            else:
                os.remove(dest_dir)
            self.send_response(conn, 267)
        self.write(conn)

    def _df(self, conn, *args, **kwargs):
        user_home_dir = self.user_data[conn].get('user_home_dir', '')
        quotation = self.user_data[conn].get('quotation', '')
        data = {
            'quotation': quotation,
            'used': get_quotation(user_home_dir)
        }
        self.send_response(conn, 269, data=data)
        self.write(conn)

    def _exit(self, conn, *args, **kwargs):
        self.send_response(conn, 271)
        self.selector.unregister(conn)
        del self.user_data[conn]
        conn.close()