#!/usr/bin/env python3
"""Pymodbus asynchronous Server with updating task Example.

An example of an asynchronous server and
a task that runs continuously alongside the server and updates values.

usage::

    server_updating.py [-h] [--comm {tcp,udp,serial,tls}]
                       [--framer {ascii,rtu,socket,tls}]
                       [--log {critical,error,warning,info,debug}]
                       [--port PORT] [--store {sequential,sparse,factory,none}]
                       [--slaves SLAVES]

    -h, --help
        show this help message and exit
    -c, --comm {tcp,udp,serial,tls}
        set communication, default is tcp
    -f, --framer {ascii,rtu,socket,tls}
        set framer, default depends on --comm
    -l, --log {critical,error,warning,info,debug}
        set log level, default is info
    -p, --port PORT
        set port
        set serial device baud rate
    --store {sequential,sparse,factory,none}
        set datastore type
    --slaves SLAVES
        set number of slaves to respond to

The corresponding client can be started as:
    python3 client_sync.py
"""
import asyncio
import logging
import sys
import os
import pdb
import random
import json
import pymodbus

try:
    import server_async
except ImportError:
    print("*** ERROR --> THIS EXAMPLE needs the example directory, please see \n\
          https://pymodbus.readthedocs.io/en/latest/source/examples.html\n\
          for more information.")
    sys.exit(-1)

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)

_logger = logging.getLogger(__name__)

dtDict = {}
# TODO PATHLIB THIS MAFAKA
argFile = "dt.json"
SLAVE_ID = 0x00

# global for access by both setup and update
rd_reg_cnt = 1              # number of input registers used
rd_output_coil_cnt = 2      # number of output coils used
rd_direct_input_cnt = 4       # number of direct inputs

rd_output_coil_address = 0
rd_direct_input_address = rd_output_coil_address+rd_output_coil_cnt + 1
rd_reg_address = rd_direct_input_address+rd_direct_input_cnt+1

DATABLOCK_SIZE = rd_reg_address + rd_reg_cnt

# 'input' parameters
BIG_RED_BUTTON = 0                 # initial state of the Big Red Button 
DRAIN_BUTTON = 0               # initial state of the Drain button
MAX_TANK_LEVEL = 1000       # largest number of tank level units
TANK_INPUT_RATE = 10.0        # flow rate of input when on
TANK_OUTPUT_RATE = 7.5        # drain rate of output when on 
TANK_LEVEL = 500             # current level of the tank
TANK_HIGH_LEVEL = 900         # position of the 'high' sensor           
TANK_LOW_LEVEL = 100          # position of the 'low' sensor
UPDATE_RATE = 1.0            # number of seconds @ tank update
TCP_PORT = 5020             # TCP over which 


updates = 0
def initDT(dtDict):
    global TANK_INPUT_RATE, TANK_OUTPUT_RATE, TCP_PORT, UPDATE_RATE, BIG_RED_BUTTON, DRAIN_BUTTON
    global MAX_TANK_LEVEL, TANK_LEVEL, TANK_HIGH_LEVEL, TANK_LOW_LEVEL

    if 'inputRate' in dtDict:
        TANK_INPUT_RATE = dtDict['inputRate']

    assert TANK_INPUT_RATE >= 0.0, "inputRate should be non-negative"

    if 'outputRate' in dtDict:
        TANK_OUTPUT_RATE = dtDict['outputRate']

    assert TANK_OUTPUT_RATE >= 0.0, "outputRate should be non-negative"

    if updates==0 and 'port' in dtDict:
        TCP_PORT = dtDict['port']

    assert TCP_PORT==502 or 5000 < TCP_PORT < 10000, "port should either be 502 or in (5000,10000)"

    if 'update' in dtDict:
        UPDATE_RATE = dtDict['update']

    assert 0.0 < UPDATE_RATE < 10.0, "update should be positive and less than 10 seconds"

    if 'brb' in dtDict:
        BIG_RED_BUTTON = dtDict['brb']

    assert BIG_RED_BUTTON==0 or BIG_RED_BUTTON==1, "BRB value should be 0 or 1"

    if 'drain' in dtDict:
        DRAIN_BUTTON = dtDict['drain']

    assert DRAIN_BUTTON==0 or DRAIN_BUTTON==1, "Drain value should be 0 or 1"

    if updates==0 and 'tankLevels' in dtDict:
        MAX_TANK_LEVEL = dtDict['tankLevels']

    assert 10 <= MAX_TANK_LEVEL <= 1000, "tankLevel should be in [10,1000]"

    if updates==0 and 'level' in dtDict:
        TANK_LEVEL = dtDict['level']

    assert 0 <= TANK_LEVEL <= MAX_TANK_LEVEL, "initial level should be in [0,{}]".format(MAX_TANK_LEVEL)

    if updates==0 and 'highLevel' in dtDict:
        TANK_HIGH_LEVEL = dtDict['highLevel']

    assert 0 < TANK_HIGH_LEVEL <= MAX_TANK_LEVEL, "highLevel should be in (0,{}]".format(MAX_TANK_LEVEL)

    if updates==0 and 'lowLevel' in dtDict:
        TANK_LOW_LEVEL = dtDict['lowLevel']

    assert 0 < TANK_LOW_LEVEL < TANK_HIGH_LEVEL, "highLevel should be in (0,{}]".format(TANK_HIGH_LEVEL)

# map from symbolic names of coils, direct inputs, input registers to the
# index in the tankState array that holds the values
#
COIL_MAP =  {'INPUT':0,'OUTPUT':1}
INPUT_MAP = {'BRB':0,'DRAIN':1,'HIGH':2,'LOW':3}
REGISTER_MAP = {'LEVEL':0}

# define arrays to hold the output coils, direct inputs, and input registers 
'''
    coils[0] is control to INPUT
    coils[1] is control to OUTPUT
    inputs[0] is state of BRB
    inputs[1] is state of drain button
    inputs[2] is state of 'high' sensor
    inputs[3] is state of 'low' sensor
    registers[0] is state of water level in tank
'''
initCoils = [0]*2
initInputs = [0]*4
initRegs = [0]*1
initInputs[2] = 0 if TANK_LEVEL < TANK_HIGH_LEVEL else 1
initInputs[3] = 0 if TANK_LEVEL < TANK_LOW_LEVEL else 1
initRegs[0] = TANK_LEVEL
TANK_STATE = {'coils':initCoils, 'inputs':initInputs, 'registers':initRegs}

def update_inputs(context):
    print("entered update_inputs()")
    global TANK_INPUT_RATE, TANK_OUTPUT_RATE
    with open(argFile,'r') as rf:
        dtDict = json.load(rf)

    print('read json file')
    if 'inputRate' in dtDict:
        TANK_INPUT_RATE = dtDict['inputRate']

    assert TANK_INPUT_RATE > 0.0, "inputRate should be positive"

    if 'outputRate' in dtDict:
        TANK_OUTPUT_RATE = dtDict['outputRate']

    assert TANK_OUTPUT_RATE > 0.0, "outputRate should be positive"

    if 'brb' in dtDict:
        brb = dtDict['brb']

    assert brb==0 or brb==1, "BRB value should be 0 or 1"
        
    if 'drain' in dtDict:
        drains = dtDict['drain']

    assert DRAIN_BUTTON==0 or DRAIN_BUTTON==1, "DRAIN value should be 0 or 1"

    TANK_STATE['inputs'][INPUT_MAP['BRB']] = 1 if brb else 0
    TANK_STATE['inputs'][INPUT_MAP['DRAIN']] = 1 if DRAIN_BUTTON else 0

def update_tank_state(context):
    print("entered update tank state")
    global TANK_LEVEL

    update_inputs(context)
    print(TANK_STATE)

    # increase the tank level only if the INPUT output coil state is on (1) and the Big Red Button is on (1)
    if TANK_STATE['coils'][COIL_MAP['INPUT']] > 0 and TANK_STATE['inputs'][INPUT_MAP['BRB']] > 0:
        TANK_LEVEL += UPDATE_RATE*TANK_INPUT_RATE

    # decrease the tank level only if the OUTPUT output coil state is on (1) and the Drain button is on (1)
    if TANK_STATE['coils'][COIL_MAP['OUTPUT']] > 0 and TANK_STATE['inputs'][INPUT_MAP['DRAIN']] > 0:
        TANK_LEVEL -= UPDATE_RATE*TANK_OUTPUT_RATE

    # N.B. if we want not both INPUT and OUTPUT to be set, it is the job of the Modbus master to issue
    # controls to the coils to enforce that.

    # if the water level hits 1000 or drops below 0, the
    # physical protection will change an output coil.  Built-in safety feature for the tank
    if MAX_TANK_LEVEL <= TANK_LEVEL :
        TANK_LEVEL = MAX_TANK_LEVEL
        TANK_STATE['coils'][COIL_MAP['INPUT']] = 0        # turn the input control off
    elif TANK_LEVEL <= 0 :
        TANK_LEVEL = 0
        TANK_STATE['coils'][COIL_MAP['OUTPUT']] = 0       # turn the output control off

    # change the state of the input register that records the state of the tank
    TANK_STATE['registers'][REGISTER_MAP['LEVEL']] = int(TANK_LEVEL)

    # set the threshold direct inputs
    TANK_STATE['inputs'][INPUT_MAP['HIGH']] = 1 if TANK_HIGH_LEVEL <= TANK_LEVEL else 0
    TANK_STATE['inputs'][INPUT_MAP['LOW']] = 1 if TANK_LOW_LEVEL <= TANK_LEVEL else 0

    TANK_STATE['inputs'][INPUT_MAP['BRB']] = 1 if BIG_RED_BUTTON==1 else 0
    TANK_STATE['inputs'][INPUT_MAP['DRAIN']] = 1 if DRAIN_BUTTON==1 else 0

    print(f"Level: {TANK_LEVEL}")

async def updating_task(context):
    """Update values in server.

    This task runs continuously beside the server
    It will increment some values each update

    It should be noted that getValues and setValues are not safe
    against concurrent use.
    """
    rd_reg_as_hex = 0x03 
    rd_output_coil_as_hex = 0x01
    rd_direct_input_as_hex = 0x02


    # set values to initial values. not sure why initial getValues is needed, but server_updating.py has it
    context[SLAVE_ID].getValues(rd_reg_as_hex, rd_reg_address, count=len(TANK_STATE['registers']))
    context[SLAVE_ID].setValues(rd_reg_as_hex, rd_reg_address, TANK_STATE['registers'])

    context[SLAVE_ID].getValues(rd_output_coil_as_hex, rd_output_coil_address, count=len(TANK_STATE['coils']))
    context[SLAVE_ID].setValues(rd_output_coil_as_hex, rd_output_coil_address, TANK_STATE['coils'])

    context[SLAVE_ID].getValues(rd_direct_input_as_hex, rd_direct_input_address, count=len(TANK_STATE['inputs']))
    context[SLAVE_ID].setValues(rd_direct_input_as_hex, rd_direct_input_address, TANK_STATE['inputs'])

    # incrementing loop
    while True:
        print(f"Level: {TANK_LEVEL}, waiting...")
        await asyncio.sleep(UPDATE_RATE)
        print(f"Done sleeping")

        update_tank_state(context)
        print("Updated tank state")

        # fetch the coil and direct inputs from the data store
        coil_values  = context[SLAVE_ID].getValues(rd_output_coil_as_hex, rd_output_coil_address, count=len(TANK_STATE['coils']))
        print("coil values", coil_values)

        input_values = context[SLAVE_ID].getValues(rd_direct_input_as_hex, rd_direct_input_address, count=len(TANK_STATE['inputs']))

        # make the input_values reflect what is in tankState, as these are externally applied
        input_values[INPUT_MAP['BRB']] = TANK_STATE['inputs'][INPUT_MAP['BRB']]
        input_values[INPUT_MAP['DRAIN']] = TANK_STATE['inputs'][INPUT_MAP['DRAIN']]

        # set INPUT coil to OFF if level is at max or if BRB is not on
        if (MAX_TANK_LEVEL <= TANK_LEVEL) or input_values[INPUT_MAP['BRB']] == 0 or coil_values[COIL_MAP['INPUT']] == 0:
            coil_values[COIL_MAP['INPUT']] = 0 

        # set OUTPUT coil to OFF if level is at 0 or if DRAIN is not on
        if TANK_LEVEL <=0 or input_values[INPUT_MAP['DRAIN']]==0 or coil_values[COIL_MAP['OUTPUT']] == 0:
            coil_values[COIL_MAP['OUTPUT']] = 0 

        TANK_STATE['coils'] = coil_values
        print("tank coil values", TANK_STATE['coils'])

        # save coil updates
        context[SLAVE_ID].setValues(rd_output_coil_as_hex, rd_output_coil_address, TANK_STATE['coils'])

        # save the BRB and DRAIN inputs to the tankState
        TANK_STATE['inputs'][INPUT_MAP['BRB']] = input_values[INPUT_MAP['BRB']]
        TANK_STATE['inputs'][INPUT_MAP['DRAIN']] = input_values[INPUT_MAP['DRAIN']]

        # the inputs for high and low may have changed though so write the input states back
        context[SLAVE_ID].setValues(rd_direct_input_as_hex, rd_direct_input_address, TANK_STATE['inputs'])

        # the input register may have changed
        context[SLAVE_ID].setValues(rd_reg_as_hex, rd_reg_address, TANK_STATE['registers'])

        txt = f"updating_task: updated coil values: {TANK_STATE['coils']!s}, input values {TANK_STATE['inputs']!s}, register values {TANK_STATE['registers']!s}" 
        print(txt)
        #_logger.debug(txt)


def setup_updating_server(cmdline=None):
    """Run server setup."""
    # The datastores only respond to the addresses that are initialized
    # If you initialize a DataBlock to addresses of 0x00 to 0xFF, a request to
    # 0x100 will respond with an invalid address exception.
    # This is because many devices exhibit this kind of behavior (but not all)

    # Continuing, use a sequential block 
    datablock = ModbusSequentialDataBlock(SLAVE_ID, [0]*DATABLOCK_SIZE)
    context = ModbusSlaveContext(di=datablock, co=datablock, hr=datablock, ir=datablock)
    context = ModbusServerContext(slaves=context, single=True)
    return server_async.setup_server(
        description="Run asynchronous server.", context=context, cmdline=cmdline
    )


async def run_updating_server(args):
    """Start updating_task concurrently with the current task."""
    task = asyncio.create_task(updating_task(args.context))
    task.set_name("example updating task")
    await server_async.run_async_server(args)  # start the server
    task.cancel()


async def main(cmdline=None):
    run_args = setup_updating_server(cmdline=cmdline)
    await run_updating_server(run_args)


if __name__ == "__main__":
    # first argument is name of file where digital twin arguments reside 
    if not len(sys.argv) < 2:
        #argFile = os.path.join('/tmp', sys.argv[1])
        argFile = os.path.join('.', sys.argv[1])
        try:
            with open(argFile,'r') as rf:
                dtDict = json.load(rf)
        except:
            print("error opening argument file {}\n".format(argFile))
            exit(1)
        sys.argv.pop(1)

    initDT(dtDict)
    """Combine setup and run."""
    asyncio.run(main(), debug=True)