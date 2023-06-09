from random import randint
import sys
import traceback
import threading
import socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket
import time


class ServerWorker:
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    STARTAGAIN = 'STARTAGAIN'
    SPEEDUP = 'SPEEDUP'
    SLOWDOWN = 'SLOWDOWN'
    DESCRIBE = 'DESCRIBE'
    SWITCH = 'SWITCH'

    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2

    speed_change = [0.025, 0.05, 0.075]
    speed_pos = 1

    SPEED = speed_change[1]

    clientInfo = {}

    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        self.clientInfo['sent_packet_count'] = 0

    def run(self):
        threading.Thread(target=self.recvRtspRequest).start()

    def recvRtspRequest(self):
        """Receive RTSP request from the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        while True:
            data = connSocket.recv(256)
            if data:
                print("Data received:\n" + data.decode("utf-8"))
                self.processRtspRequest(data.decode("utf-8"))

    def processRtspRequest(self, data):
        """Process RTSP request sent from the client."""
        # Get the request type
        request = data.split('\n')
        line1 = request[0].split(' ')
        requestType = line1[0]

        # Get the media file name
        filename = line1[1]

        # Get the RTSP sequence number
        seq = request[1].split(' ')

        # Process SETUP request
        if requestType == self.SETUP:
            if self.state == self.INIT:
                # Update state
                print("processing SETUP\n")
                # print(f"rtspSocket = {self.clientInfo['rtspSocket']}")

                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    self.state = self.READY
                    self.totalFrame = self.clientInfo['videoStream'].getTotalFrame(
                    )
                    # print(f"Total Frame: {self.totalFrame}")
                except IOError:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])

                # Generate a randomized RTSP session ID
                self.clientInfo['session'] = randint(100000, 999999)

                # Send RTSP reply
                self.replyRtsp(self.OK_200, seq[1], requestType)

                # Get the RTP/UDP port from the last line
                self.clientInfo['rtpPort'] = request[2].split(' ')[3]
        # Process PLAY request
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("processing PLAY\n")
                self.state = self.PLAYING

                # Create a new socket for RTP/UDP
                self.clientInfo["rtpSocket"] = socket.socket(
                    socket.AF_INET, socket.SOCK_DGRAM)

                self.replyRtsp(self.OK_200, seq[1])

                # Create a new thread and start sending RTP packets
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(
                    target=self.sendRtp)
                self.clientInfo['worker'].start()

        # Process PAUSE request
        elif requestType == self.PAUSE:
            # if self.state == self.PLAYING:
            print("processing PAUSE\n")
            self.state = self.READY

            self.clientInfo['event'].set()

            self.replyRtsp(self.OK_200, seq[1])

        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")
            self.SPEED = self.speed_change[1]

            try:  # if the rtp socket has been setup
                self.clientInfo['event'].set()
                # Close the RTP socket
                self.clientInfo['rtpSocket'].close()
            except:
                pass

            self.replyRtsp(self.OK_200, seq[1])

        # Process STARTAGAIN request
        elif requestType == self.STARTAGAIN:
            if self.state != self.INIT:
                self.clientInfo['videoStream'].currentFile().close()
                self.clientInfo['videoStream'] = VideoStream(filename)

                print("processing STARTAGAIN\n")

                self.clientInfo['event'].set()
                # Create a new socket for RTP/UDP
                self.clientInfo["rtpSocket"] = socket.socket(
                    socket.AF_INET, socket.SOCK_DGRAM)
                self.state = self.PLAYING

                # Create a new thread and start sending RTP packets
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(
                    target=self.sendRtp)
                self.clientInfo['worker'].start()
                self.replyRtsp(self.OK_200, seq[1])

        # Process SPEEDUP request
        elif requestType == self.SPEEDUP:
            if self.state != self.INIT:
                # if self.SPEED > 0.025:

                if self.speed_pos > 0:
                    self.speed_pos = self.speed_pos - 1
                    self.SPEED = self.speed_change[self.speed_pos]
                print(f"Speed: {self.SPEED}")
                print("processing SPEEDUP\n")

        # Process SLOWDOWN request
        elif requestType == self.SLOWDOWN:
            if self.state != self.INIT:

                if self.speed_pos < 2:
                    self.speed_pos = self.speed_pos + 1
                    self.SPEED = self.speed_change[self.speed_pos]
                print(f"Speed: {self.SPEED}")
                print("processing SLOWDOWN\n")

        # Process DESCRIBE request
        elif requestType == self.DESCRIBE:
            if self.state != self.INIT:
                self.replyRtsp(self.OK_200, seq[1], requestType)

        elif requestType == self.SWITCH:
            if self.state != self.INIT:
                self.clientInfo['videoStream'].currentFile().close()
                self.clientInfo['videoStream'] = VideoStream(filename)
                print("processing SWITCH\n")

                self.clientInfo['event'].set()
                # Create a new socket for RTP/UDP
                self.clientInfo["rtpSocket"] = socket.socket(
                    socket.AF_INET, socket.SOCK_DGRAM)
                # self.state = self.PLAYING

                # Create a new thread and start sending RTP packets
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(
                    target=self.sendRtp)
                self.clientInfo['worker'].start()
                self.replyRtsp(self.OK_200, seq[1])

    def sendRtp(self):
        """Send RTP packets over UDP."""
        while True:
            self.clientInfo['event'].wait(self.SPEED)

            # Stop sending if request is PAUSE or TEARDOWN
            if self.clientInfo['event'].isSet():
                break

            data = self.clientInfo['videoStream'].nextFrame()
            if data:
                frameNumber = self.clientInfo['videoStream'].frameNbr()
                try:
                    address = self.clientInfo['rtspSocket'][1][0]
                    port = int(self.clientInfo['rtpPort'])

                    self.clientInfo['rtpSocket'].sendto(
                        self.makeRtp(data, frameNumber), (address, port))
                    self.clientInfo['sent_packet_count'] += 1
                except:
                    print("Connection Error")
                    # print('-'*60)
                    # traceback.print_exc(file=sys.stdout)
                    # print('-'*60)

    def makeRtp(self, payload, frameNbr):
        """RTP-packetize the video data."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        marker = 0
        pt = 26  # MJPEG type
        seqnum = frameNbr
        ssrc = 0

        rtpPacket = RtpPacket()

        rtpPacket.encode(version, padding, extension, cc,
                         seqnum, marker, pt, ssrc, payload)

        return rtpPacket.getPacket()

    def replyRtsp(self, code, seq, requestType=""):
        """Send RTSP reply to the client."""
        if code == self.OK_200:
            # print("200 OK")
            reply = 'RTSP/1.0 200 OK\nCSeq: ' + seq + \
                '\nSession: ' + str(self.clientInfo['session'])
            if requestType == self.SETUP:
                reply += f"\nTotal frame: {self.totalFrame}"
            elif requestType == self.DESCRIBE:
                # reply += f"\nSession ID: {self.clientInfo['session']}\nFile name: {self.clientInfo['videoStream'].filename}\nStream type: real-time\nEncoding: MJPEG\nProtocol: RTP/RTSP1.0\nRequests count: {seq}\n{self.clientInfo['sent_packet_count']}"
                reply += f"\nSession ID: {self.clientInfo['session']}\nFile name: {self.clientInfo['videoStream'].filename}\nStream type: real-time\nEncoding: MJPEG\nProtocol: RTP/RTSP1.0\nRequests count: {seq}\nPacket sent: {self.clientInfo['sent_packet_count']}"
            elif requestType in [self.PLAY, self.STARTAGAIN, self.SLOWDOWN, self.STARTAGAIN]:
                reply += f"\nSent time: {time.time()}"
            connSocket = self.clientInfo['rtspSocket'][0]
            # print('connSocket', connSocket)
            connSocket.send(reply.encode())

        # Error messages
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")
