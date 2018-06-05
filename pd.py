##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2012 Joel Holdsworth <joel@airwebreathe.org.uk>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
##

import sigrokdecode as srd
import struct

'''
OUTPUT_PYTHON format:

Packet:
[<ptype>, <pdata>]

<ptype>, <pdata>:
 - 'DATA', [<channel>, <value>]

<channel>: 'L' or 'R'
<value>: integer
'''

class SamplerateError(Exception):
    pass

class Decoder(srd.Decoder):
    api_version = 2
    id = 'i2s_4ch_export'
    name = 'I²S 4ch export'
    longname = 'Integrated Interchip Sound 4ch export'
    desc = 'Serial bus for connecting digital audio devices. 4ch export'
    license = 'gplv2+'
    inputs = ['logic']
    outputs = ['i2s']
    channels = (
        {'id': 'sck', 'name': 'SCK', 'desc': 'Bit clock line'},
        {'id': 'ws', 'name': 'WS', 'desc': 'Word select line'},
        {'id': 'sd0', 'name': 'SD0', 'desc': 'Serial data line'},
        {'id': 'sd1', 'name': 'SD1', 'desc': 'Serial data line'},
        {'id': 'sd2', 'name': 'SD2', 'desc': 'Serial data line'},
        {'id': 'sd3', 'name': 'SD3', 'desc': 'Serial data line'},
    )
    annotations = (
        ('left', 'Left channel'),
        ('right', 'Right channel'),
        ('warnings', 'Warnings'),
    )
    binary = (
        ('wav', 'WAV file'),
    )
    options = (
        {'id': 'word_length', 'desc': 'word length', 'default': 16, 'values': (12,16,20,24.32)},
    )

    def __init__(self):
        self.samplerate = None
        self.oldsck = 1
        self.oldws = 1
        self.bitcount = 0
        self.data_all = [0,0,0,0]
        self.samplesreceived = 0
        self.first_sample = None
        self.ss_block = None
        self.wordlength = -1
        self.wrote_wav_header = False
        self.fout = [open("ch0L.pcm", 'wb', 0),open("ch0R.pcm", 'wb', 0),
                     open("ch1L.pcm", 'wb', 0),open("ch1R.pcm", 'wb', 0),
                     open("ch2L.pcm", 'wb', 0),open("ch2R.pcm", 'wb', 0),
                     open("ch3L.pcm", 'wb', 0),open("ch3R.pcm", 'wb', 0)]

    def start(self):
        self.out_python = self.register(srd.OUTPUT_PYTHON)
        self.out_binary = self.register(srd.OUTPUT_BINARY)
        self.out_ann = self.register(srd.OUTPUT_ANN)

    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    def putpb(self, data):
        self.put(self.ss_block, self.samplenum, self.out_python, data)

    def putbin(self, data):
        self.put(self.ss_block, self.samplenum, self.out_binary, data)

    def putb(self, data):
        self.put(self.ss_block, self.samplenum, self.out_ann, data)

    def report(self):

        # Calculate the sample rate.
        samplerate = '?'
        if self.ss_block is not None and \
            self.first_sample is not None and \
            self.ss_block > self.first_sample:
            samplerate = '%d' % (self.samplesreceived *
                self.samplerate / (self.ss_block -
                self.first_sample))

        return 'I²S: %d %d-bit samples received at %sHz' % \
            (self.samplesreceived, self.wordlength, samplerate)

    def wav_header(self):
        # Chunk descriptor
        h  = b'RIFF'
        h += b'\x24\x80\x00\x00' # Chunk size (2084)
        h += b'WAVE'
        # Fmt subchunk
        h += b'fmt '
        h += b'\x10\x00\x00\x00' # Subchunk size (16 bytes)
        h += b'\x01\x00'         # Audio format (0x0001 == PCM)
        h += b'\x02\x00'         # Number of channels (2)
        h += b'\x80\x3e\x00\x00' # Samplerate (16000)
        h += b'\x00\x7d\x00\x00' # Byterate (32000)
        h += b'\x04\x00'         # Blockalign (4)
        h += b'\x10\x00'         # Bits per sample (16)
        # Data subchunk
        h += b'data'
        h += b'\xff\xff\x00\x00' # Subchunk size (65535 bytes) TODO
        return h

    def wav_sample(self, sample):
        # TODO: This currently assumes U32 samples, and converts to S16.
        s = sample >> 16
        if s >= 0x8000:
            s -= 0x10000
        lo, hi = s & 0xff, (s >> 8) & 0xff
        return bytes([lo, hi])

    def decode(self, ss, es, data):
        if not self.samplerate:
            raise SamplerateError('Cannot decode without samplerate.')
        for self.samplenum, (sck, ws, sd0, sd1, sd2, sd3) in data:
            data.itercnt += 1
            # Ignore sample if the bit clock hasn't changed.
            if sck == self.oldsck:
                continue

            self.oldsck = sck
            if sck == 0:   # Ignore the falling clock edge.
                continue

            if self.bitcount >= self.options['word_length']:
                sd0,sd1,sd2,sd3 = 0,0,0,0;

            self.data_all[0] = (self.data_all[0] << 1) | sd0;
            self.data_all[1] = (self.data_all[1] << 1) | sd1;
            self.data_all[2] = (self.data_all[2] << 1) | sd2;
            self.data_all[3] = (self.data_all[3] << 1) | sd3;
            self.bitcount += 1

            # This was not the LSB unless WS has flipped.
            if ws == self.oldws:
                continue

            # Only submit the sample, if we received the beginning of it.
            if self.ss_block is not None:

                if not self.wrote_wav_header:
                    self.put(0, 0, self.out_binary, [0, self.wav_header()])
                    self.wrote_wav_header = True

                self.samplesreceived += 1

                idx = 0 if self.oldws else 1
                c1 = 'Left channel' if self.oldws else 'Right channel'
                c2 = 'Left' if self.oldws else 'Right'
                c3 = 'L' if self.oldws else 'R'
                v = '%04x %04x %04x %04x' % tuple(self.data_all)
                self.putpb(['DATA', [c3, self.data_all]])
                self.putb([idx, ['%s: %s' % (c1, v), '%s: %s' % (c2, v),
                                 '%s: %s' % (c3, v), c3]])
                #self.putbin([0, self.wav_sample(self.data)])
                self.save_data(self.oldws, *self.data_all)

                # Check that the data word was the correct length.
                if self.wordlength != -1 and self.wordlength != self.bitcount:
                    self.putb([2, ['Received %d-bit word, expected %d-bit '
                                   'word' % (self.bitcount, self.wordlength)]])

                self.wordlength = self.bitcount

            # Reset decoder state.
            self.data_all = [0,0,0,0]
            self.bitcount = 0
            self.ss_block = self.samplenum

            # Save the first sample position.
            if self.first_sample is None:
                self.first_sample = self.samplenum

            self.oldws = ws

    def save_data(self, ws, data0, data1, data2, data3):
        if self.options['word_length'] == 12:
            pack_config_string = "H"
            shift_config = 4
        elif self.options['word_length'] == 16:
            pack_config_string = "H"
            shift_config = 0
        elif self.options['word_length'] == 20:
            pack_config_string = "I"
            shift_config = 12
        elif self.options['word_length'] == 24:
            pack_config_string = "I"
            shift_config = 8
        elif self.options['word_length'] == 32:
            pack_config_string = "I"
            shift_config = 0

        self.fout[0+ws].write(struct.pack(pack_config_string, data0<<shift_config))
        self.fout[2+ws].write(struct.pack(pack_config_string, data1<<shift_config))
        self.fout[4+ws].write(struct.pack(pack_config_string, data2<<shift_config))
        self.fout[6+ws].write(struct.pack(pack_config_string, data3<<shift_config))
