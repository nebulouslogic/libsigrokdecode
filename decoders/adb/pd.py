##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2022 Mike Everhart <mike@nebulouslogic.com>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##

import sigrokdecode as srd

class SamplerateError(Exception):
    pass

# Timing values in us for the signal
timing = {
    'RESET':            3000.0,     # 3 ms
    'RESET_TOL':        100.0,      # 100 us
    'ATTENTION':        800.0,      # 800 us
    'ATTENTION_TOL':    24.0,       # 3% of 800 us
    'SYNC':             65.0,       # 65 us
    'SYNC_TOL':         2.0,        # 3% of 65 us
    'BIT_CELL':         100.0,      # 100 us
    'BIT_CELL_TOL':     30.0,       # 30% of 10 us (Device Tolerance, Host is only 3%)
    'BIT_0_LOW':        65.0,       # 65% of BIT_CELL
    'BIT_0_LOW_TOL':    5.0,        # 5% of BIT_CELL
    'BIT_1_LOW':        35.0,       # 35% of BIT_CELL
    'BIT_1_LOW_TOL':    5.0,        # 5% of BIT_CELL
    'STOP':             70.0,       # 70 us
    'STOP_TOL':         21.0,       # 30% of STOP (Device Tolerance, Host is only 3%)
    'STOP_SREQ':        300.0,      # 300 us
    'STOP_SREQ_TOL':    90.0,       # 30% of STOP_SREQ (Stop bit with Service Request)
    'TLT':              200.0,      # 200 us (Stop-bit-to-Start-bit)
    'TLT_TOL':          60.0,       # 60 us (140 us min, 260 us max)
}

'''
OUTPUT_PYTHON format:

Packet:
[<ptype>, <pdata>]

<ptype>:
 - 'START' (START condition)
 - 'START REPEAT' (Repeated START condition)
 - 'ADDRESS READ' (Slave address, read)
 - 'ADDRESS WRITE' (Slave address, write)
 - 'DATA READ' (Data, read)
 - 'DATA WRITE' (Data, write)
 - 'STOP' (STOP condition)
 - 'ACK' (ACK bit)
 - 'NACK' (NACK bit)
 - 'BITS' (<pdata>: list of data/address bits and their ss/es numbers)

<pdata> is the data or address byte associated with the 'ADDRESS*' and 'DATA*'
command. Slave addresses do not include bit 0 (the READ/WRITE indication bit).
For example, a slave address field could be 0x51 (instead of 0xa2).
For 'START', 'START REPEAT', 'STOP', 'ACK', and 'NACK' <pdata> is None.
'''

# CMD: [annotation-type-index, long annotation, short annotation]
proto = {
    'START':           [0, 'Start',         'S'],
    'START REPEAT':    [1, 'Start repeat',  'Sr'],
    'STOP':            [2, 'Stop',          'P'],
    'ACK':             [3, 'ACK',           'A'],
    'NACK':            [4, 'NACK',          'N'],
    'BIT':             [5, 'Bit',           'B'],
    'ADDRESS READ':    [6, 'Address read',  'AR'],
    'ADDRESS WRITE':   [7, 'Address write', 'AW'],
    'DATA READ':       [8, 'Data read',     'DR'],
    'DATA WRITE':      [9, 'Data write',    'DW'],
}

class Decoder(srd.Decoder):
    api_version = 3
    id = 'adb'
    name = 'ADB'
    longname = 'Apple Desktop Bus'
    desc = 'One-wire, single-master, multi-drop, serial bus.'
    license = 'gplv3+'
    inputs = ['logic']
    outputs = ['adb']
    optional_channels = ()
    tags = ['Retro computing']
    channels = (
        {'id': 'adb', 'name': 'ADB', 'desc': 'ADB data line'},
    )
    options = (
        {'id': 'tolerance', 'desc': 'Timing Tolerance',
            'default': 'strict', 'values': ('strict', 'relaxed')},
    )
    annotations = (
        ('reset', 'Bus reset'),                 # 0
        ('attention', 'Attention condition'),   # 1
        ('sync', 'Sync condition'),             # 2
        ('start', 'Start bit'),                 # 3
        ('stop', 'Stop bit'),                   # 4
        ('addr', 'Address bit'),                # 5
        ('cmd', 'Command bit'),                 # 6
        ('reg', 'Register bit'),                # 7
        ('dat', 'Data bit'),                    # 8
        ('tlt', 'Stop-bit-to-start-bit delay'), # 9
        ('srq', 'Service request'),             # 10
        ('command', 'Command'),                 # 11
        ('address', 'Device address'),          # 12
        ('register', 'Register'),               # 13
        ('data', 'Data'),                       # 14
        ('warning', 'Warning'),                 # 15
    )
    annotation_rows = (
        ('bus', 'Bus', (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10,)),
        ('transactions', 'Transactions', (11, 12, 13, 14,)),
        ('warnings', 'Warnings', (15,)),
    )

    def __init__(self):
        self.reset()

    def reset(self):
        self.samplerate = None
        self.state = 'ATTENTION'
        self.bit = 0
        self.bit_count = -1
        self.address = 0
        self.command = 0
        self.reg = 0
        self.data_word = 0
        self.fall = 0
        self.rise = 0
        self.tstart = 0
        self.tend = 0
        self.sample_addr_start = 0
        self.sample_cmd_start = 0
        self.sample_reg_start = 0
        self.sample_data_start = 0
        self.done = False

    def start(self):
        # self.out_python = self.register(srd.OUTPUT_PYTHON)
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.bit = 0
        self.bit_count = -1
        self.address = 0
        self.command = 0
        self.reg = 0
        self.data_word = 0
        self.fall = 0
        self.rise = 0
        self.tstart = 0
        self.tend = 0
        self.sample_addr_start = 0
        self.sample_cmd_start = 0
        self.sample_reg_start = 0
        self.sample_data_start = 0
        self.done = False

    def putm(self, data):
        self.put(0, 0, self.out_ann, data)

    def putpfs(self, data):
        self.put(self.fall, self.samplenum, self.out_python, data)

    def putfs(self, data):
        self.put(self.fall, self.samplenum, self.out_ann, data)

    def putfr(self, data):
        self.put(self.fall, self.rise, self.out_ann, data)

    def putprs(self, data):
        self.put(self.rise, self.samplenum, self.out_python, data)

    def putrs(self, data):
        self.put(self.rise, self.samplenum, self.out_ann, data)

    def checks(self):
        # Check if samplerate is appropriate.
        if self.samplerate < 400000:
            self.putm([1, ['Sampling rate is too low. Must be above ' +
                            '400kHz for proper normal mode decoding.']])
        elif self.samplerate < 1000000:
            self.putm([1, ['Sampling rate is suggested to be above ' +
                            '1MHz for proper normal mode decoding.']])

    def check_tolerance(self, width, type):
        if self.options['tolerance'] == 'strict':
            tolerance = timing[type + '_TOL']
        else:
            # For relaxed tolerance, use 10% looser tilerance
            tolerance = (timing[type + '_TOL'] * 1.1)
        if width >= (timing[type] - tolerance) and \
            width <= (timing[type] + tolerance):
            return True
        else:
            return False

    def metadata(self, key, value):
        if key != srd.SRD_CONF_SAMPLERATE:
            return
        self.samplerate = value

    def decode(self):
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')
        self.checks()
        while True:
            # TODO: Handle async reset
            # if time >= (timing['RESET'] - timing['RESET_TOL']):
            #     self.putfs([0, ['Bus Reset', 'Reset', 'RST', 'R']])
            
            # State machine.
            if self.state == 'ATTENTION':
                self.address = 0
                self.command = 0
                self.reg = 0
                self.data_word = 0
                self.bit_count = 0

                # Need to find ATTENTION to properly decode transaciton
                # ATTENTION is a low pulse of > 800 us
                # New session or previously the state machine aborted
                # Search for a new low pulse long enough to be an attention pulse
                if self.done == False:
                    # Unknown state or previous transaction didn't complete
                    # (if the previous transaction completed, then it ate the
                    # falling edge of the attention pulse)
                    self.wait({0: 'f'})
                    self.fall = self.samplenum
                self.wait({0: 'r'})
                self.rise = self.samplenum
                time = ((self.rise - self.fall) / self.samplerate) * 1000000.0
                if time >= (timing['ATTENTION'] - timing['ATTENTION_TOL']):
                    # found an ATTENTION pulse, try to decode a transaction
                    self.putfs([1, ['Bus Attention', 'Attention', 'ATTN', 'A']])
                    self.state = 'SYNC'
                    self.tstart = self.samplenum
                else:
                    # return to top, process another low pulse
                    pass
                self.done = False
            elif self.state == 'SYNC':
                self.wait({0: 'f'})
                self.fall = self.samplenum
                time = ((self.fall - self.rise) / self.samplerate) * 1000000.0
                if self.check_tolerance(time, 'SYNC'):
                    self.putrs([2, ['Sync', 'SS']])
                    self.state = 'COMMAND'
                else:
                    # TODO: Error reporting on bad sync width
                    # Return to ATTENTION state to look for an ATTENTION pulse
                    self.state = 'ATTENTION'
            elif self.state == 'COMMAND':
                self.bit_count = 0
                while self.bit_count < 8:
                    # Each bit is made up of 3 edges - falling, rising, falling
                    # '0's are bits where the low period is >= 65% of the bit period
                    # '1's are bits there the high period is >= 65% of the bit period
                    if self.bit_count == 0:
                        ann_id = 5  # 4 address bits
                        self.sample_addr_start = self.samplenum
                    elif self.bit_count == 4:
                        ann_id = 6  # 2 command bits
                        self.sample_cmd_start = self.samplenum
                        # Done with the address, add the address annotation
                        self.put(self.sample_addr_start, self.samplenum, self.out_ann, [12, ["Address: " + str(hex(self.address))]])
                    elif self.bit_count == 6:
                        ann_id = 7  # 2 register bits
                        self.sample_reg_start = self.samplenum
                        # Done with the command, add the command annotation
                        if self.command == 0:
                            command = ['Flush', 'Flsh', 'Fl', 'F']
                        elif self.command == 2:
                            command = ['Listen', 'Lst', 'L']
                        elif self.command == 3:
                            command = ['Talk', 'Tlk', 'T']
                        self.put(self.sample_cmd_start, self.samplenum, self.out_ann, [11, command])
                    bit_start = self.samplenum
                    self.fall = self.samplenum
                    self.wait({0: 'r'})
                    bit_mid = self.samplenum
                    self.rise = self.samplenum
                    self.wait({0: 'f'})
                    bit_end = self.samplenum
                    bit_low = ((bit_mid - bit_start) / self.samplerate) * 1000000.0
                    bit_high = ((bit_end - bit_mid) / self.samplerate) * 1000000.0
                    bit_cell = bit_low + bit_high
                    # TODO: add better bit width checking
                    if (bit_low / bit_cell) > 0.6:
                        self.bit = 0
                        self.putfs([ann_id, [str(self.bit)]])
                    elif (bit_high / bit_cell) > 0.6:
                        self.bit = 1
                        self.putfs([ann_id, [str(self.bit)]])
                    else:
                        # TODO: Error reporting on bad bit width
                        # Return to ATTENTION state to look for an ATTENTION pulse
                        self.state = 'ATTENTION'
                    # update self.fall after 'put' annotation
                    self.fall = self.samplenum
                    if self.bit_count < 4: # 4 bits of address
                        self.address = self.address + (self.bit << (3 - self.bit_count))
                    elif self.bit_count < 6: # 2 bits of command
                        self.command = self.command + (self.bit << (5 - self.bit_count))
                    elif self.bit_count < 8: # 2 bits of register
                        self.reg = self.reg + (self.bit << (7 - self.bit_count))
                    else:
                        pass
                    self.bit_count += 1
                # Done with the register, add the register annotation
                self.put(self.sample_reg_start, self.samplenum, self.out_ann, [13, ["Register: " + str(hex(self.reg))]])
                self.state = 'STOP_CMD'
            elif self.state == 'STOP_CMD':
                self.wait({0: 'r'})
                self.rise = self.samplenum
                time = ((self.rise - self.fall) / self.samplerate) * 1000000.0
                if self.check_tolerance(time, 'STOP'):
                    self.putfs([4, ['STOP','ST']])
                    self.state = 'TLT'
                elif self.check_tolerance(time, 'STOP_SREQ'):
                    self.putfs([10, ['Service Request', 'SREQ', 'SR']])
                    self.state = 'TLT'
                else:
                    # TODO error reporting
                    # Return to ATTENTION state to look for an ATTENTION pulse
                    self.state = 'ATTENTION'
            elif self.state == 'TLT':
                self.wait({0: 'f'})
                self.fall = self.samplenum
                time = ((self.fall - self.rise) / self.samplerate) * 1000000.0
                if self.check_tolerance(time, 'TLT'):
                    self.putrs([9, ['Stop-to-Start','TLT']])
                    self.state = 'START_DATA'
                else:
                    # End of a transaction with no data phase
                    # Return to ATTENTION state to look for an ATTENTION pulse
                    self.state = 'ATTENTION'
                    # set a flag that we ate the falling edge of the attention,
                    # so no need to look for one
                    self.done = True
            elif self.state == 'START_DATA':
                # Each bit is made up of 3 edges - falling, rising, falling
                # '0's are bits where the low period is >= 65% of the bit period
                # '1's are bits there the high period is >= 65% of the bit period
                bit_start = self.samplenum
                self.fall = self.samplenum
                self.wait({0: 'r'})
                bit_mid = self.samplenum
                self.rise = self.samplenum
                self.wait({0: 'f'})
                bit_end = self.samplenum
                bit_low = ((bit_mid - bit_start) / self.samplerate) * 1000000.0
                bit_high = ((bit_end - bit_mid) / self.samplerate) * 1000000.0
                bit_cell = bit_low + bit_high
                # TODO: add better bit width checking
                if (bit_high / bit_cell) > 0.6:
                    self.state = 'DATA'
                    self.putfs([3, ['Start', 'St']])
                else:
                    # TODO: Error reporting on bad bit width
                    # Return to ATTENTION state to look for an ATTENTION pulse
                    self.state = 'ATTENTION'
                # update self.fall after 'put' annotation
                self.fall = self.samplenum
            elif self.state == 'DATA':
                self.bit_count = 0
                self.sample_data_start = self.samplenum
                while self.bit_count < 16:
                    # Each bit is made up of 3 edges - falling, rising, falling
                    # '0's are bits where the low period is >= 65% of the bit period
                    # '1's are bits there the high period is >= 65% of the bit period
                    bit_start = self.samplenum
                    self.fall = self.samplenum
                    self.wait({0: 'r'})
                    bit_mid = self.samplenum
                    self.rise = self.samplenum
                    self.wait({0: 'f'})
                    bit_end = self.samplenum
                    bit_low = ((bit_mid - bit_start) / self.samplerate) * 1000000.0
                    bit_high = ((bit_end - bit_mid) / self.samplerate) * 1000000.0
                    bit_cell = bit_low + bit_high
                    # TODO: add better bit width checking
                    if (bit_low / bit_cell) > 0.6:
                        self.bit = 0
                        self.bit_count += 1
                        self.putfs([8, [str(self.bit)]])
                    elif (bit_high / bit_cell) > 0.6:
                        self.bit = 1
                        self.bit_count += 1
                        self.putfs([8, [str(self.bit)]])
                    else:
                        # TODO: Error reporting on bad bit width
                        # Return to ATTENTION state to look for an ATTENTION pulse
                        self.state = 'ATTENTION'
                    # push data bit onto data word
                    self.data_word = self.data_word + (self.bit << (16 - self.bit_count))
                    # update self.fall after 'put' annotation
                    self.fall = self.samplenum
                # Done with the data read/write, add the data word annotation
                self.put(self.sample_data_start, self.samplenum, self.out_ann, [14, ["Data: 0x{:04x}".format(self.data_word)]])
                self.state = 'STOP_DATA'
            elif self.state == 'STOP_DATA':
                self.wait({0: 'r'})
                self.rise = self.samplenum
                time = ((self.rise - self.fall) / self.samplerate) * 1000000.0
                if self.check_tolerance(time, 'STOP'):
                    self.putfs([4, ['STOP','ST']])
                elif self.check_tolerance(time, 'STOP_SREQ'):
                    self.putfs([10, ['Service Request', 'SREQ', 'SR']])
                else:
                    # TODO error reporting
                    # Return to ATTENTION state to look for an ATTENTION pulse
                    self.state = 'ATTENTION'
                self.state = 'ATTENTION'
            else:
                pass