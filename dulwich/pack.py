# pack.py -- For dealing wih packed git objects.
# Copyright (C) 2007 James Westby <jw+debian@jameswestby.net>
# Copryight (C) 2008 Jelmer Vernooij <jelmer@samba.org>
# The code is loosely based on that in the sha1_file.c file from git itself,
# which is Copyright (C) Linus Torvalds, 2005 and distributed under the
# GPL version 2.
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# of the License.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.

"""Classes for dealing with packed git objects.

A pack is a compact representation of a bunch of objects, stored
using deltas where possible.

They have two parts, the pack file, which stores the data, and an index
that tells you where the data is.

To find an object you look in all of the index files 'til you find a
match for the object name. You then use the pointer got from this as
a pointer in to the corresponding packfile.
"""

import hashlib
import mmap
import os
import struct
import sys

supports_mmap_offset = (sys.version_info[0] >= 3 or 
        (sys.version_info[0] == 2 and sys.version_info[1] >= 6))

from objects import (ShaFile,
                     _decompress,
                     )

hex_to_sha = lambda hex: int(hex, 16)

MAX_MMAP_SIZE = 256 * 1024 * 1024

def simple_mmap(f, offset, size, access=mmap.ACCESS_READ):
    if offset+size > MAX_MMAP_SIZE and not supports_mmap_offset:
        raise AssertionError("%s is larger than 256 meg, and this version "
            "of Python does not support the offset argument to mmap().")
    if supports_mmap_offset:
        return mmap.mmap(f.fileno(), size, access=access, offset=offset)
    else:
        class ArraySkipper(object):

            def __init__(self, array, offset):
                self.array = array
                self.offset = offset

            def __getslice__(self, i, j):
                return self.array[i+self.offset:j+self.offset]

            def __getitem__(self, i):
                return self.array[i+self.offset]

            def __len__(self):
                return len(self.array) - self.offset

            def __str__(self):
                return str(self.array[self.offset:])

        mem = mmap.mmap(f.fileno(), size+offset, access=access)
        if offset == 0:
            return mem
        return ArraySkipper(mem, offset)


def multi_ord(map, start, count):
    value = 0
    for i in range(count):
        value = value * 0x100 + ord(map[start+i])
    return value


class PackIndex(object):
  """An index in to a packfile.

  Given a sha id of an object a pack index can tell you the location in the
  packfile of that object if it has it.

  To do the loop it opens the file, and indexes first 256 4 byte groups
  with the first byte of the sha id. The value in the four byte group indexed
  is the end of the group that shares the same starting byte. Subtract one
  from the starting byte and index again to find the start of the group.
  The values are sorted by sha id within the group, so do the math to find
  the start and end offset and then bisect in to find if the value is present.
  """

  PACK_INDEX_HEADER_SIZE = 0x100 * 4
  index_size = 4
  sha_bytes = 20
  record_size = sha_bytes + index_size

  def __init__(self, filename):
    """Create a pack index object.

    Provide it with the name of the index file to consider, and it will map
    it whenever required.
    """
    self._filename = filename
    assert os.path.exists(filename), "%s is not a pack index" % filename
    # Take the size now, so it can be checked each time we map the file to
    # ensure that it hasn't changed.
    self._size = os.path.getsize(filename)
    self._fan_out_table = self._read_fan_out_table()

  def __len__(self):
    ret = 0
    for v in self._fan_out_table.itervalues():
        ret += v
    return v

  def _read_fan_out_table(self):
    f = open(self._filename, 'r')
    try:
        contents = f.read(256 * 4)
    finally:
        f.close()
    ret = {}
    for i in range(0x100):
        (ret[i],) = struct.unpack(">L", contents[i*4:(i+1)*4])
    return ret

  def check(self):
    """Check that the stored checksum matches the actual checksum."""
    return self.get_checksum() == self.get_stored_checksum()

  def get_checksum(self):
    f = open(self._filename, 'r')
    try:
        contents = simple_mmap(f, 0, self._size-20)
        return hashlib.sha1(contents).digest()
    finally:
        f.close()

  def get_stored_checksum(self):
    """Return the SHA1 checksum stored for this header file itself."""
    f = open(self._filename, 'r')
    try:
        return str(simple_mmap(f, self._size-20, 20))
    finally:
        f.close()

  def object_index(self, sha):
    """Return the index in to the corresponding packfile for the object.

    Given the name of an object it will return the offset that object lives
    at within the corresponding pack file. If the pack file doesn't have the
    object then None will be returned.
    """
    size = os.path.getsize(self._filename)
    assert size == self._size, "Pack index %s has changed size, I don't " \
         "like that" % self._filename
    f = open(self._filename, 'rb')
    try:
      map = simple_mmap(f, 0, size)
      return self._object_index(map, sha)
    finally:
      f.close()

  def _entry_offset(self, i):
      return self.PACK_INDEX_HEADER_SIZE + (i * self.record_size)

  def _object_index(self, map, hexsha):
      """See object_index"""
      first_byte = hex_to_sha(hexsha[:2])
      header_offset = 4 * first_byte
      start = multi_ord(map, header_offset-4, 4)
      end = multi_ord(map, header_offset, 4)
      sha = hex_to_sha(hexsha)
      while start < end:
        i = (start + end)/2
        offset = self._entry_offset(i)
        file_sha = multi_ord(map, offset + self.index_size, self.sha_bytes)
        if file_sha == sha:
          return multi_ord(map, offset, self.index_size)
        elif file_sha < sha:
          start = offset + 1
        else:
          end = offset - 1
      return None


class PackData(object):
  """The data contained in a packfile.

  Pack files can be accessed both sequentially for exploding a pack, and
  directly with the help of an index to retrieve a specific object.

  The objects within are either complete or a delta aginst another.

  The header is variable length. If the MSB of each byte is set then it
  indicates that the subsequent byte is still part of the header.
  For the first byte the next MS bits are the type, which tells you the type
  of object, and whether it is a delta. The LS byte is the lowest bits of the
  size. For each subsequent byte the LS 7 bits are the next MS bits of the
  size, i.e. the last byte of the header contains the MS bits of the size.

  For the complete objects the data is stored as zlib deflated data.
  The size in the header is the uncompressed object size, so to uncompress
  you need to just keep feeding data to zlib until you get an object back,
  or it errors on bad data. This is done here by just giving the complete
  buffer from the start of the deflated object on. This is bad, but until I
  get mmap sorted out it will have to do.

  Currently there are no integrity checks done. Also no attempt is made to try
  and detect the delta case, or a request for an object at the wrong position.
  It will all just throw a zlib or KeyError.
  """

  def __init__(self, filename):
    """Create a PackData object that represents the pack in the given filename.

    The file must exist and stay readable until the object is disposed of. It
    must also stay the same size. It will be mapped whenever needed.

    Currently there is a restriction on the size of the pack as the python
    mmap implementation is flawed.
    """
    self._filename = filename
    assert os.path.exists(filename), "%s is not a packfile" % filename
    self._size = os.path.getsize(filename)
    self._read_header()

  def _read_header(self):
    f = open(self._filename, 'rb')
    try:
        header = f.read(12)
    finally:
        f.close()
    assert header[:4] == "PACK"
    (version,) = struct.unpack_from(">L", header, 4)
    assert version in (2, 3), "Version was %d" % version
    (self._num_objects,) = struct.unpack_from(">L", header, 8)

  def __len__(self):
      """Returns the number of objects in this pack."""
      return self._num_objects

  def get_object_at(self, offset):
    """Given an offset in to the packfile return the object that is there.

    Using the associated index the location of an object can be looked up, and
    then the packfile can be asked directly for that object using this
    function.

    Currently only non-delta objects are supported.
    """
    assert isinstance(offset, long) or isinstance(offset, int)
    size = os.path.getsize(self._filename)
    assert size == self._size, "Pack data %s has changed size, I don't " \
         "like that" % self._filename
    f = open(self._filename, 'rb')
    try:
      map = simple_mmap(f, offset, size-offset)
      return self._get_object_at(map)
    finally:
      f.close()

  def _get_object_at(self, map):
    first_byte = ord(map[0])
    sign_extend = first_byte & 0x80
    type = (first_byte >> 4) & 0x07
    size = first_byte & 0x0f
    cur_offset = 0
    while sign_extend > 0:
      byte = ord(map[cur_offset+1])
      sign_extend = byte & 0x80
      size_part = byte & 0x7f
      size += size_part << ((cur_offset * 7) + 4)
      cur_offset += 1
    raw_base = cur_offset+1
    # The size is the inflated size, so we have no idea what the deflated size
    # is, so for now give it as much as we have. It should really iterate
    # feeding it more data if it doesn't decompress, but as we have the whole
    # thing then just use it.
    raw = map[raw_base:]
    uncomp = _decompress(raw)
    obj = ShaFile.from_raw_string(type, uncomp)
    return obj


def write_pack(filename, objects):
    """Write a new pack file.

    :param filename: The filename of the new pack file.
    :param objects: List of objects to write.
    """
    f = open(filename, 'w')
    try:
        f.write("PACK")               # Pack header
        f.write(struct.pack(">L", 2)) # Pack version
        f.write(struct.pack(">L", len(objects))) # Number of objects in pack
        for o in objects:
            pass # FIXME: Write object
    finally:
        f.close()
