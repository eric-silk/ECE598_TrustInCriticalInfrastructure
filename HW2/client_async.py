#!/usr/bin/env python3
"""Pymodbus asynchronous client example.

usage::

    client_async.py [-h] [-c {tcp,udp,serial,tls}]
                    [-f {ascii,rtu,socket,tls}]
                    [-l {critical,error,warning,info,debug}] [-p PORT]
                    [--baudrate BAUDRATE] [--host HOST]

    -h, --help
        show this help message and exit
    -c, -comm {tcp,udp,serial,tls}
        set communication, default is tcp
    -f, --framer {ascii,rtu,socket,tls}
        set framer, default depends on --comm
    -l, --log {critical,error,warning,info,debug}
        set log level, default is info
    -p, --port PORT
        set port
    --baudrate BAUDRATE
        set serial device baud rate
    --host HOST
        set host, default is 127.0.0.1

The corresponding server must be started before e.g. as:
    python3 server_sync.py
"""
import asyncio
import time
import logging
import sys
import pdb

from dataclasses import dataclass

try:
    import helper
    import addressing_info as ai
except ImportError as e:
    print(e)
    sys.exit(-1)

import pymodbus.client as modbusClient
from pymodbus import ModbusException


_logger = logging.getLogger(__file__)
logging.basicConfig(filename="async_client.log", level=logging.DEBUG)
_logger.setLevel("DEBUG")


def setup_async_client(description=None, cmdline=None):
    """Run client setup."""
    args = helper.get_commandline(
        server=False, description=description, cmdline=cmdline
    )
    _logger.info("### Create client object")
    client = None
    if args.comm == "tcp":
        client = modbusClient.AsyncModbusTcpClient(
            args.host,
            port=args.port,  # on which port
            # Common optional parameters:
            framer=args.framer,
            timeout=args.timeout,
            retries=3,
            reconnect_delay=1,
            reconnect_delay_max=10,
            #    source_address=("localhost", 0),
        )
    elif args.comm == "udp":
        client = modbusClient.AsyncModbusUdpClient(
            args.host,
            port=args.port,
            # Common optional parameters:
            framer=args.framer,
            timeout=args.timeout,
            #    retries=3,
            # UDP setup parameters
            #    source_address=None,
        )
    elif args.comm == "serial":
        client = modbusClient.AsyncModbusSerialClient(
            args.port,
            # Common optional parameters:
            #    framer=ModbusRtuFramer,
            timeout=args.timeout,
            #    retries=3,
            # Serial setup parameters
            baudrate=args.baudrate,
            #    bytesize=8,
            #    parity="N",
            #    stopbits=1,
            #    handle_local_echo=False,
        )
    elif args.comm == "tls":
        client = modbusClient.AsyncModbusTlsClient(
            args.host,
            port=args.port,
            # Common optional parameters:
            framer=args.framer,
            timeout=args.timeout,
            #    retries=3,
            # TLS setup parameters
            sslctx=modbusClient.AsyncModbusTlsClient.generate_ssl(
                certfile=helper.get_certificate("crt"),
                keyfile=helper.get_certificate("key"),
                #    password="none",
            ),
        )
    else:
        raise RuntimeError(f"Unknown commtype {args.comm}")
    return client


async def run_async_client(client, modbus_calls=None):
    """Run sync client."""
    _logger.info("### Client starting")
    await client.connect()
    assert client.connected
    if modbus_calls:
        await modbus_calls(client)
    client.close()
    _logger.info("### End of Program")


@dataclass
class TankState:
    input_coil_on: bool
    output_coil_on: bool
    big_red_button: bool
    drain_output: bool
    high_sensor: bool
    low_sensor: bool
    level: int


class WaterTankController:
    MAX_LEVEL = 900
    MIN_LEVEL = 100

    def __init__(self, client):
        self.client = client

    async def control_loop(self) -> None:
        state = await self._read_state()
        if state.level > self.MAX_LEVEL:
            print("Warning: tank level exceeded 900 units!")
            await self._flow_out()
        if state.level < self.MIN_LEVEL:
            print("Warning: tank level fell below 100 units!")
            await self._flow_in()

        if self.MIN_LEVEL <= state.level <= self.MAX_LEVEL:
            # Valid region
            pass

    async def _read_state(self) -> TankState:
        rr = await self.client.read_coils(0, 2, slave=1)
        output_coils = rr.bits
        input_coil = output_coils[0]
        output_coil = output_coils[1]

        rr = await self.client.read_discrete_inputs(3, 4, slave=1)
        input_flags = rr.bits
        brb = input_flags[0]
        drain = input_flags[1]
        high = input_flags[2]
        low = input_flags[3]

        rr = await self.client.read_holding_registers(8, 1, slave=1)
        register_values = rr.registers
        level = register_values[0]

        state = TankState(input_coil, output_coil, brb, drain, high, low, level)
        print(f"State: {state}")

        return state

    async def _flow_in(self):
        await self._disable_drain()
        await self._enable_input()

    async def _flow_out(self):
        await self._disable_input()
        await self._enable_drain()

    async def _enable_drain(self):
        await self.client.write_coil(1, 1, slave=1)

    async def _disable_drain(self):
        await self.client.write_coil(1, 0, slave=1)

    async def _enable_input(self):
        await self.client.write_coil(0, 1, slave=1)

    async def _disable_input(self):
        await self.client.write_coil(0, 0, slave=1)


async def run_a_few_calls(client):
    """Test connection works."""
    controller = WaterTankController(client)
    await controller._flow_in()
    while True:
        try:
            await controller._read_state()
            await controller._flow_in()
            time.sleep(0.5)

        except ModbusException as e:
            print(f"Exception occurred:\n{e}")
            pass


async def main(cmdline=None):
    """Combine setup and run."""
    testclient = setup_async_client(description="Run client.", cmdline=cmdline)
    await run_async_client(testclient, modbus_calls=run_a_few_calls)


if __name__ == "__main__":
    asyncio.run(main(), debug=True)
