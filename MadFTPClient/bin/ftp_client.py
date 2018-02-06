# coding:utf-8

import os
import sys
import socket
import hashlib
import json
import getpass
from optparse import OptionParser

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from conf import settings
from common import set_password

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


class FTPClient(object):
    def __init__(self):
        # 读取输入参数
        self.username = None
        self.offset = ''
        self.parser = OptionParser()
        self.parser.add_option("-s", "--server", dest="server", help="ftp  server ip addr")
        self.parser.add_option("-P", "--port", type=int, dest="port", help="ftp server port")
        self.parser.add_option("-u", "--username", dest="username", help="username")
        self.parser.add_option("-p", "--password", dest="password", help="password")
        (self.options, self.args) = self.parser.parse_args()
        self.verify_args()
        self.make_connection()

    def make_connection(self):
        # 建立socket连接
        self.sock = socket.socket()
        self.sock.connect((self.options.server, self.options.port))

    def verify_args(self):
        """
        效验参数合法性
        """
        # 必要参数：server、port
        if self.options.server and self.options.port:
            if 0 < self.options.port < 65535:
                # 用户名密码需成对出现
                if bool(self.options.username) is bool(self.options.password):
                    return True
                else:
                    exit("Error: username and password must be provided together")
            else:
                exit("Error: host port must in 0-65535")
        else:
            exit(self.parser.print_help())

    def authenticate(self):
        """
        用户验证
        """
        if self.options.username:
            return self.get_auth_result(self.options.username, self.options.password)
        else:
            retry_count = 0
            while retry_count < 3:
                username = raw_input("username: ").strip()
                password = getpass.getpass("password: ").strip()
                if self.get_auth_result(username, password):
                    return True
                retry_count += 1
            else:
                print "You have tried too many times, exit..."

    def get_auth_result(self, username, password):
        # 生成token
        token = set_password(password, settings.SALT_VALUE)
        data = {
            'action': 'auth',
            'username': username,
            'token': token
        }
        # 发送认证请求
        # 先dumps后encode
        self.send_response(data)
        response = self.get_response()
        if response.get('status_code') == 254:
            print "Passed authentication"
            self.username = username
            return True
        else:
            print response.get('status_msg')

    def get_response(self):
        """
        统一处理服务端发送的请求
        """
        data = self.sock.recv(1024)
        # 先decode后loads
        data = json.loads(data.decode('utf-8'))
        print "response: ", data
        return data

    def send_response(self, data):
        """
        统一处理返回服务端数据,不包括传输数据
        """
        data = json.dumps(data).encode('utf-8')
        print "send: ", data
        return self.sock.send(data)

    def interactive(self):
        if self.authenticate():
            print "start interactive with you"
            while True:
                choice = raw_input('[%s]:' % self.username).strip()
                if len(choice) == 0:
                    continue
                # 构造函数名，避免关键字冲突
                # 反射不支持私有方法
                cmd_list = choice.split()
                action = cmd_list[0]
                action_func = "_%s" % action
                if action:
                    if hasattr(self, action_func):
                        func = getattr(self, action_func)
                        func(cmd_list)
                else:
                    print("invalid cmd")

    def output_prefix(self):
        if self.username:
            return '[%s]:' % self.username
        else:
            return ''

    def _exit(self, cmd_list):
        print "exit----"
        data_header = {
            'action': 'exit',
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 271:
            self.sock.close()
            exit('Log Out.')

    def _get(self, cmd_list):
        print "get----"
        if len(cmd_list) == 1:
            print "no filename follows"
            return
        data_header = {
            'action': 'get',
            'filename': cmd_list[1],
            'offset': self.offset,
        }
        base_filename = cmd_list[1].split('/')[-1]
        filepath = settings.USER_HOME + '/' + self.username + '/' + base_filename
        ret = os.path.isfile(filepath)
        if not ret:
            received_size = 0
            file_obj = open(filepath, 'wb')
        else:
            received_size = os.path.getsize(filepath)
            file_obj = open(filepath, 'ab')
        data_header.update(recvsize=received_size)
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 257:
            filesize = reponse.get('filesize', 0)
            print filesize, received_size
            self.send_response('1')
            while received_size < filesize:
                if received_size >= filesize - 4096:
                    buffersize = filesize - received_size
                else:
                    buffersize = 4096
                data = self.sock.recv(buffersize)
                file_obj.write(data)
                received_size += len(data)
            else:
                print("----->file rece done-----")
                file_obj.close()
        else:
            file_obj.close()
            os.remove(filepath)
            print 'file not exists'

    def _put(self, cmd_list):
        print "put----"
        if len(cmd_list) == 1:
            print "no filename follows"
            return
        filename = cmd_list[1]
        base_filename = cmd_list[1].split('/')[-1]
        if os.path.isfile(filename):
            file_size = os.path.getsize(filename)
            data_header = {
                'action': 'put',
                'filename': base_filename,
                'filesize': file_size,
                'offset': self.offset,
            }
            self.send_response(data_header)
            reponse = self.get_response()
            status_code = reponse.get("status_code")
            if status_code == 270:
                print "full quotation, you have no space to put file"
                return
            if status_code == 259 or status_code == 268:
                file_obj = open(filename, "rb")
                if status_code == 268:
                    print("continue to put file")
                    received_size = reponse.get("recvsize", 0)
                    # 移动到已接收位置
                    file_obj.seek(received_size)
                else:
                    print("ready to put file")

                for line in file_obj:
                    self.sock.send(line)
                else:
                    file_obj.close()
                    print "send file done..."
            else:
                print "invalid response"
        else:
            print 'file not exists'

    def _ls(self, cmd_list):
        print "ls----"
        data_header = {
            'action': 'ls',
            'offset': self.offset
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 266:
            ls_list = reponse.get('ls', '').split(',')
            for l in ls_list:
                print l

    def _cd(self, cmd_list):
        print "cd----"
        if len(cmd_list) == 1:
            print "no dir follows"
            return
        filedir = cmd_list[1]
        data_header = {
            'action': 'cd',
            'offset': self.offset,
            'filedir': filedir
        }
        self.send_response(data_header)
        reponse = self.get_response()
        status_code = reponse.get("status_code")
        if status_code == 263:
            print "cd ok"
            self.offset = reponse.get('offset', '')
        if status_code == 264:
            print "dir not exists"
        if status_code == 265:
            self.offset = reponse.get('offset', '')
            print "can not cd upper dir"

    def _pwd(self, cmd_list):
        print "pwd----"
        data_header = {
            'action': 'pwd',
            'offset': self.offset
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 260:
            print reponse.get('pwd')

    def _mkdir(self, cmd_list):
        print "mkdir----"
        if len(cmd_list) == 1:
            print "no dir follows"
            return
        filedir = cmd_list[1]
        data_header = {
            'action': 'mkdir',
            'offset': self.offset,
            'filedir': filedir
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 261:
            print "create ok"
        if reponse.get("status_code") == 262:
            print "dir already exists"

    def _rm(self, cmd_list):
        print "rm----"
        if len(cmd_list) == 1:
            print "no dir follows"
            return
        filedir = cmd_list[1]
        data_header = {
            'action': 'rm',
            'offset': self.offset,
            'filedir': filedir
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 267:
            print "rm ok"
        if reponse.get("status_code") == 264:
            print "dir not exists"

    def _df(self, cmd_list):
        print "df----"
        data_header = {
            'action': 'df',
        }
        self.send_response(data_header)
        reponse = self.get_response()
        if reponse.get("status_code") == 269:
            print "Total: {}, Used: {}".format(reponse.get('quotation', '0'), reponse.get('used', '0'))


if __name__ == '__main__':
    ftp = FTPClient()
    # 交互
    ftp.interactive()
