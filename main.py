import requests
import websocket
import ssl
import time
import base64
import json
from PIL import Image
import pytesseract
from paddleocr import PaddleOCR
import threading
import logging
import socket

class PiKVMClient:
    def __init__(self, pikvm_ip, username='admin', password='admin'):
        self.pikvm_ip = pikvm_ip
        self.username = username
        self.password = password
        self.ws = None
        self.heartbeat_active = False
        self.heartbeat_thread = None
        self.monitor_thread = None
        self.last_successful_ping = 0
        self.connection_lock = threading.Lock()
        self.reconnect_count = 0
        self.max_reconnect_wait = 300  # 最大重连等待时间（秒）
        self.log_file = f'connection_log_{pikvm_ip.replace(".", "_")}.txt'  # 添加日志文件路径

    def log_error(self, error_type, error_message):
        """记录错误到日志文件"""
        try:
            current_time = time.strftime('%Y-%m-%d %H:%M:%S')
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(f"\n=== {current_time} ===\n")
                f.write(f"错误类型: {error_type}\n")
                f.write(f"错误信息: {error_message}\n")
        except Exception as e:
            print(f"写入日志文件失败: {e}")

    def create_websocket(self, max_retries=3):
        """建立并返回 WebSocket 连接"""
        with self.connection_lock:  # 使用锁防止并发重连
            for attempt in range(max_retries):
                try:
                    uri = f'wss://{self.pikvm_ip}/api/ws'
                    headers = {
                        'X-KVMD-User': self.username,
                        'X-KVMD-Passwd': self.password
                    }
                    
                    # 使用 enableTrace 来调试连接问题
                    websocket.enableTrace(True)
                    
                    self.ws = websocket.WebSocket(sslopt={"cert_reqs": ssl.CERT_NONE})
                    self.ws.settimeout(60)
                    
                    print(f"正在连接到 WebSocket... (第 {attempt + 1} 次尝试)")
                    self.ws.connect(uri, header=headers)
                    print("WebSocket 连接成功")
                    
                    # 设置 TCP keepalive
                    self.ws.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    if hasattr(socket, 'TCP_KEEPIDLE'):
                        self.ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
                    if hasattr(socket, 'TCP_KEEPINTVL'):
                        self.ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
                    if hasattr(socket, 'TCP_KEEPCNT'):
                        self.ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
                    
                    # 接收初始消息
                    response = self.ws.recv()
                    print("WebSocket 初始响应:", response)
                    
                    # 重置重连计数
                    self.reconnect_count = 0
                    self.last_successful_ping = time.time()
                    
                    # 启动心跳和监控
                    self.start_heartbeat()
                    self.start_connection_monitor()
                    
                    return True
                    
                except Exception as e:
                    error_message = f"WebSocket 连接失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}"
                    print(error_message)
                    self.log_error("连接失败", error_message)
                    if attempt < max_retries - 1:
                        wait_time = min(3 * (attempt + 1), 30)  # 递增等待时间
                        print(f"等待 {wait_time} 秒后重试...")
                        time.sleep(wait_time)
                    else:
                        print(f"WebSocket 连接失败，已达到最大重试次数 ({max_retries})")
                        return False

    def start_connection_monitor(self):
        """启动连接监控线程"""
        if self.monitor_thread is None or not self.monitor_thread.is_alive():
            self.monitor_thread = threading.Thread(target=self._monitor_connection)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()

    def _monitor_connection(self):
        """监控连接状态"""
        while True:
            try:
                # 检查最后一次成功ping的时间
                if time.time() - self.last_successful_ping > 30:  # 30秒无响应
                    print("检测到连接可能断开，尝试重新连接...")
                    self.reconnect()
                time.sleep(5)  # 每5秒检查一次
            except Exception as e:
                print(f"连接监控错误: {e}")
                time.sleep(5)

    def start_heartbeat(self):
        """启动心跳线程"""
        if self.heartbeat_thread is None or not self.heartbeat_thread.is_alive():
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
            self.heartbeat_thread.daemon = True
            self.heartbeat_active = True
            self.heartbeat_thread.start()

    def _heartbeat_loop(self):
        """心跳循环"""
        while self.heartbeat_active:
            try:
                if self.ws and self.ws.connected:
                    # 发送心跳消息
                    heartbeat_msg = {
                        "event_type": "ping",
                        "event": {}
                    }
                    self.ws.send(json.dumps(heartbeat_msg))
                    
                    # 等待响应
                    try:
                        self.ws.settimeout(5)
                        response = self.ws.recv()
                        self.last_successful_ping = time.time()
                    except websocket.WebSocketTimeoutException as e:
                        error_message = f"心跳响应超时: {str(e)}"
                        print(error_message)
                        self.log_error("心跳超时", error_message)
                        self.reconnect()
                    except Exception as e:
                        error_message = f"心跳接收错误: {str(e)}"
                        print(error_message)
                        self.log_error("心跳错误", error_message)
                        self.reconnect()
                    finally:
                        self.ws.settimeout(None)
                
                time.sleep(10)  # 每10秒发送一次心跳
                
            except Exception as e:
                error_message = f"心跳发送错误: {str(e)}"
                print(error_message)
                self.log_error("心跳发送失败", error_message)
                self.reconnect()
                time.sleep(5)

    def reconnect(self):
        """重新连接"""
        try:
            # 计算等待时间（指数退避）
            wait_time = min(2 ** self.reconnect_count, self.max_reconnect_wait)
            print(f"等待 {wait_time} 秒后尝试重连...")
            time.sleep(wait_time)
            
            if self.ws:
                try:
                    self.ws.close()
                except:
                    pass
                    
            if self.create_websocket():
                print("重连成功")
                self.reconnect_count = 0  # 重置计数
            else:
                error_message = f"重连失败，已尝试 {self.reconnect_count} 次"
                print(error_message)
                self.log_error("重连失败", error_message)
                self.reconnect_count += 1
                
        except Exception as e:
            error_message = f"重新连接失败: {str(e)}"
            print(error_message)
            self.log_error("重连异常", error_message)
            self.reconnect_count += 1

    def get_snapshot(self, snapshot_file='snapshot.jpg'):
        """获取快照"""
        try:
            url = f'https://{self.pikvm_ip}/api/streamer/snapshot'
            headers = {
                'X-KVMD-User': 'admin',
                'X-KVMD-Passwd': 'admin'
            }
            
            response = requests.get(
                url, 
                headers=headers,
                verify=False,
                timeout=10
            )
            
            response.raise_for_status()
            
            with open(snapshot_file, 'wb') as file:
                file.write(response.content)
            print(f"快照已保存为 '{snapshot_file}'")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"HTTP 请求失败: {e}")
            return False

    def perform_ocr(self, image_path, result_file='ocr_result.txt'):
        try:
            # 设置日志级别
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            
            # 打开原始图片
            image = Image.open(image_path)
            
            # 日发电量区域坐标 (x1, y1, x2, y2)
            region = (802, 126, 970, 170)  # 请根据实际位置调整这些坐标
            
            # 裁剪图片
            cropped_image = image.crop(region)
            
            # 保存裁剪后的图片（用于调试）
            crop_file = 'daily_power_region.jpg'
            cropped_image.save(crop_file)
            
            # 初始化 PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
            
            # 对裁剪后的图片进行OCR识别
            result = ocr.ocr(crop_file, cls=True)
            
            if result:
                text = '\n'.join([line[1][0] for line in result[0]])
                print("识别的日发电量：")
                print(text)

                # 保存识别结果到文件
                with open(result_file, 'w', encoding='utf-8') as f:
                    f.write(text)
                print(f"\nOCR 结果已保存到 {result_file}")
                return text
            else:
                print("未识别到文本")
                return None

        except Exception as e:
            print(f"OCR 识别失败: {e}")
            return None

    def close(self):
        """关闭连接"""
        self.heartbeat_active = False  # 停止心跳线程
        if self.ws:
            try:
                self.ws.close()
            except:
                pass

def main():
    try:
        # 读取多个IP地址
        ip_list = []
        while True:
            ip = input("请输入 PiKVM 设备的 IP 地址 (直接回车结束输入): ")
            if not ip:
                break
            ip_list.append(ip)
        
        if not ip_list:
            print("未输入任何IP地址，程序退出")
            return

        # 通用的认证信息
        username = input("请输入用户名 (默认为 admin): ") or 'admin'
        password = input("请输入密码 (默认为 admin): ") or 'admin'
        
        # 创建客户端字典，避免重复创建连接
        clients = {}
        for ip in ip_list:
            try:
                print(f"\n初始化连接到 IP: {ip}")
                client = PiKVMClient(ip, username, password)
                if client.create_websocket():  # 建立 WebSocket 连接
                    clients[ip] = client
            except Exception as e:
                print(f"连接 IP {ip} 失败: {e}")

        print("\n开始循环监控...")
        while True:
            current_time = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n=== 开始新一轮截图和识别 ({current_time}) ===")
            
            # 处理每个IP
            for ip, client in clients.items():
                try:
                    snapshot_file = f'snapshot_{ip.replace(".", "_")}.jpg'
                    ocr_result_file = f'ocr_result_{ip.replace(".", "_")}.txt'
                    
                    # 获取快照并识别
                    if client.get_snapshot(snapshot_file):
                        result = client.perform_ocr(snapshot_file, ocr_result_file)
                        if result:
                            log_file = f'log_{ip.replace(".", "_")}.txt'
                            with open(log_file, 'a', encoding='utf-8') as f:
                                f.write(f"\n=== {current_time} ===\n")
                                f.write(result + "\n")
                    
                except Exception as e:
                    print(f"处理 IP {ip} 时出错: {e}")
                    try:
                        print(f"尝试重新连接 WebSocket: {ip}")
                        if client.create_websocket():
                            print(f"重新连接成功: {ip}")
                        else:
                            print(f"重新连接失败: {ip}")
                    except Exception as reconnect_error:
                        print(f"重新连接时发生错误: {ip}, {reconnect_error}")
            
            print(f"\n等待1秒后开始下一轮...")
            time.sleep(1)
                    
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"发生未预期的错误: {e}")
    finally:
        print("\n正在关闭所有连接...")
        for client in clients.values():
            client.close()

if __name__ == "__main__":
    main()