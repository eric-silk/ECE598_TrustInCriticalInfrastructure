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
argFile = ""
slave_id = 0x00

# global for access by both setup and update
rd_reg_cnt = 1              # number of input registers used
rd_output_coil_cnt = 2      # number of output coils used
rd_direct_input_cnt = 4       # number of direct inputs

rd_output_coil_address = 0
rd_direct_input_address = rd_output_coil_address+rd_output_coil_cnt + 1
rd_reg_address = rd_direct_input_address+rd_direct_input_cnt+1

# 'input' parameters
brb = 0                 # initial state of the Big Red Button 
drain = 0               # initial state of the Drain button
tankLevels = 1000       # largest number of tank level units
inputRate = 10.0        # flow rate of input when on
outputRate = 7.5        # drain rate of output when on 
level = 500             # current level of the tank
highLevel = 900         # position of the 'high' sensor           
lowLevel = 100          # position of the 'low' sensor
update = 1.0            # number of seconds @ tank update
port = 5020             # TCP over which 


updates = 0
def initDT(dtDict):
    global inputRate, outputRate, port, update, brb, drain
    global tankLevels, level, highLevel, lowLevel

    if 'inputRate' in dtDict:
        inputRate = dtDict['inputRate']

    assert inputRate >= 0.0, "inputRate should be non-negative"

    if 'outputRate' in dtDict:
        outputRate = dtDict['outputRate']

    assert outputRate >= 0.0, "outputRate should be non-negative"

    if updates==0 and 'port' in dtDict:
        port = dtDict['port']

    assert port==502 or 5000 < port < 10000, "port should either be 502 or in (5000,10000)"

    if 'update' in dtDict:
        update = dtDict['update']

    assert 0.0 < update < 10.0, "update should be positive and less than 10 seconds"

    if 'brb' in dtDict:
        brb = dtDict['brb']

    assert brb==0 or brb==1, "BRB value should be 0 or 1"

    if 'drain' in dtDict:
        drain = dtDict['drain']

    assert drain==0 or drain==1, "Drain value should be 0 or 1"

    if updates==0 and 'tankLevels' in dtDict:
        tankLevels = dtDict['tankLevels']

    assert 10 <= tankLevels <= 1000, "tankLevel should be in [10,1000]"

    if updates==0 and 'level' in dtDict:
        level = dtDict['level']

    assert 0 <= level <= tankLevels, "initial level should be in [0,{}]".format(tankLevels)

    if updates==0 and 'highLevel' in dtDict:
        highLevel = dtDict['highLevel']

    assert 0 < highLevel <= tankLevels, "highLevel should be in (0,{}]".format(tankLevels)

    if updates==0 and 'lowLevel' in dtDict:
        lowLevel = dtDict['lowLevel']

    assert 0 < lowLevel < highLevel, "highLevel should be in (0,{}]".format(highLevel)

# map from symbolic names of coils, direct inputs, input registers to the
# index in the tankState array that holds the values
#
coilMap =  {'INPUT':0,'OUTPUT':1}
inputMap = {'BRB':0,'DRAIN':1,'HIGH':2,'LOW':3}
registerMap = {'LEVEL':0}

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
initInputs[2] = 0 if level < highLevel else 1
initInputs[3] = 0 if level < lowLevel else 1
initRegs[0] = level
tankState = {'coils':initCoils, 'inputs':initInputs, 'registers':initRegs}

def update_inputs(context):
    global inputRate, outputRate
    with open(argFile,'r') as rf:
        dtDict = json.load(rf)

    if 'inputRate' in dtDict:
        inputRate = dtDict['inputRate']

    assert inputRate > 0.0, "inputRate should be positive"

    if 'outputRate' in dtDict:
        outputRate = dtDict['outputRate']

    assert outputRate > 0.0, "outputRate should be positive"

    if 'brb' in dtDict:
        brb = dtDict['brb']

    assert brb==0 or brb==1, "BRB value should be 0 or 1"
        
    if 'drain' in dtDict:
        drains = dtDict['drain']

    assert drain==0 or drain==1, "DRAIN value should be 0 or 1"

    tankState['inputs'][inputMap['BRB']] = 1 if brb else 0
    tankState['inputs'][inputMap['DRAIN']] = 1 if drain else 0

def update_tank_state(context):
    global level

    update_inputs(context)
    print(tankState)

    # increase the tank level only if the INPUT output coil state is on (1) and the Big Red Button is on (1)
    if tankState['coils'][coilMap['INPUT']] > 0 and tankState['inputs'][inputMap['BRB']] > 0:
        level += update*inputRate

    # decrease the tank level only if the OUTPUT output coil state is on (1) and the Drain button is on (1)
    if tankState['coils'][coilMap['OUTPUT']] > 0 and tankState['inputs'][inputMap['DRAIN']] > 0:
        level -= update*outputRate

    # N.B. if we want not both INPUT and OUTPUT to be set, it is the job of the Modbus master to issue
    # controls to the coils to enforce that.

    # if the water level hits 1000 or drops below 0, the
    # physical protection will change an output coil.  Built-in safety feature for the tank
    if tankLevels <= level :
        level = tankLevels
        tankState['coils'][coilMap['INPUT']] = 0        # turn the input control off
    elif level <= 0 :
        level = 0
        tankState['coils'][coilMap['OUTPUT']] = 0       # turn the output control off

    # change the state of the input register that records the state of the tank
    tankState['registers'][registerMap['LEVEL']] = int(level)

    # set the threshold direct inputs
    tankState['inputs'][inputMap['HIGH']] = 1 if highLevel <= level else 0
    tankState['inputs'][inputMap['LOW']] = 1 if lowLevel <= level else 0

    tankState['inputs'][inputMap['BRB']] = 1 if brb==1 else 0
    tankState['inputs'][inputMap['DRAIN']] = 1 if drain==1 else 0

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

    slave_id = 0x00

    # set values to initial values. not sure why initial getValues is needed, but server_updating.py has it
    context[slave_id].getValues(rd_reg_as_hex, rd_reg_address, count=len(tankState['registers']))
    context[slave_id].setValues(rd_reg_as_hex, rd_reg_address, tankState['registers'])

    context[slave_id].getValues(rd_output_coil_as_hex, rd_output_coil_address, count=len(tankState['coils']))
    context[slave_id].setValues(rd_output_coil_as_hex, rd_output_coil_address, tankState['coils'])

    context[slave_id].getValues(rd_direct_input_as_hex, rd_direct_input_address, count=len(tankState['inputs']))
    context[slave_id].setValues(rd_direct_input_as_hex, rd_direct_input_address, tankState['inputs'])

    # incrementing loop
    while True:
        await asyncio.sleep(update)

        update_tank_state(context)

        # fetch the coil and direct inputs from the data store
        coil_values  = context[slave_id].getValues(rd_output_coil_as_hex, rd_output_coil_address, count=len(tankState['coils']))
        print("coil values", coil_values)

        input_values = context[slave_id].getValues(rd_direct_input_as_hex, rd_direct_input_address, count=len(tankState['inputs']))

        # make the input_values reflect what is in tankState, as these are externally applied
        input_values[inputMap['BRB']] = tankState['inputs'][inputMap['BRB']]
        input_values[inputMap['DRAIN']] = tankState['inputs'][inputMap['DRAIN']]

        # set INPUT coil to OFF if level is at max or if BRB is not on
        if (tankLevels <= level) or input_values[inputMap['BRB']] == 0 or coil_values[coilMap['INPUT']] == 0:
            coil_values[coilMap['INPUT']] = 0 

        # set OUTPUT coil to OFF if level is at 0 or if DRAIN is not on
        if level <=0 or input_values[inputMap['DRAIN']]==0 or coil_values[coilMap['OUTPUT']] == 0:
            coil_values[coilMap['OUTPUT']] = 0 

        tankState['coils'] = coil_values
        print("tank coil values", tankState['coils'])

        # save coil updates
        context[slave_id].setValues(rd_output_coil_as_hex, rd_output_coil_address, tankState['coils'])

        # save the BRB and DRAIN inputs to the tankState
        tankState['inputs'][inputMap['BRB']] = input_values[inputMap['BRB']]
        tankState['inputs'][inputMap['DRAIN']] = input_values[inputMap['DRAIN']]

        # the inputs for high and low may have changed though so write the input states back
        context[slave_id].setValues(rd_direct_input_as_hex, rd_direct_input_address, tankState['inputs'])

        # the input register may have changed
        context[slave_id].setValues(rd_reg_as_hex, rd_reg_address, tankState['registers'])

        txt = f"updating_task: updated coil values: {tankState['coils']!s}, input values {tankState['inputs']!s}, register values {tankState['registers']!s}" 
        #print(txt)
        #_logger.debug(txt)


def setup_updating_server(cmdline=None):
    """Run server setup."""
    # The datastores only respond to the addresses that are initialized
    # If you initialize a DataBlock to addresses of 0x00 to 0xFF, a request to
    # 0x100 will respond with an invalid address exception.
    # This is because many devices exhibit this kind of behavior (but not all)

    # Continuing, use a sequential block 
    datablock = ModbusSequentialDataBlock(0x00, [0]*(rd_direct_input_address+rd_direct_input_cnt))
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
