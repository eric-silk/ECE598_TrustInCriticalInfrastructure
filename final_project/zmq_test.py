from typing import Dict, Tuple
import time
import multiprocessing as mp

import zmq
import json


PUB_SLEEP_SECONDS = 1
SUB_SLEEP_SECONDS = 0.1

addr1 = "tcp://127.0.0.1:61802"
addr2 = "tcp://127.0.0.2:61802"


class PubAgent:
    def __init__(self, addr: str, agent_id: int) -> None:
        self.addr = addr
        self.agent_id = agent_id

        self.context = zmq.Context()

        self.pub_sock = self.context.socket(zmq.PUB)
        self.pub_sock.bind(self.addr)

    def __call__(self) -> None:
        i = 0
        while True:
            message = bytes(json.dumps(f"Test Message {i}"), encoding="UTF-8")
            topic = bytes(f"{self.agent_id}", encoding="UTF-8")
            self.pub_sock.send_multipart([topic, message])
            i += 1
            time.sleep(PUB_SLEEP_SECONDS)


class SubAgent:
    def __init__(self, addr: str, agent_id: int, sub_id: Tuple[int, str]) -> None:
        self.addr = addr
        self.agent_id = agent_id

        self.context = zmq.Context()

        self.sub_sock = self.context.socket(zmq.SUB)
        self.sub_sock.connect(sub_id[1])
        self.sub_sock.setsockopt_string(zmq.SUBSCRIBE, str(sub_id[0]))

    def __call__(self) -> None:
        while True:
            topic, msg = self.sub_sock.recv_multipart()
            print(f"Received from {topic}: {msg}")
            time.sleep(SUB_SLEEP_SECONDS)


if __name__ == "__main__":
    pub = PubAgent(addr1, 1)
    sub = SubAgent(addr2, 2, (1, addr1))

    p1 = mp.Process(target=pub)
    p1.start()

    try:
        sub()
    except:
        pass

    p1.join()
