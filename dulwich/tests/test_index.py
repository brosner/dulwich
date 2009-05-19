# test_index.py -- Tests for the git index cache
# Copyright (C) 2008 Jelmer Vernooij <jelmer@samba.org>
# 
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2
# or (at your option) any later version of the License.
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


"""Tests for the index."""


import os
import stat
from unittest import TestCase

from dulwich.index import (
    Index,
    commit_tree,
    read_index,
    write_index,
    )
from dulwich.object_store import (
    MemoryObjectStore,
    )
from dulwich.objects import (
    Blob,
    )

class IndexTestCase(TestCase):

    datadir = os.path.join(os.path.dirname(__file__), 'data/indexes')

    def get_simple_index(self, name):
        return Index(os.path.join(self.datadir, name))


class SimpleIndexTestcase(IndexTestCase):

    def test_len(self):
        self.assertEquals(1, len(self.get_simple_index("index")))

    def test_iter(self):
        self.assertEquals(['bla'], list(self.get_simple_index("index")))

    def test_getitem(self):
        self.assertEquals( ((1230680220, 0), (1230680220, 0), 2050, 3761020, 33188, 1000, 1000, 0, 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391', 0)
            , 
                self.get_simple_index("index")["bla"])


class SimpleIndexWriterTestCase(IndexTestCase):

    def test_simple_write(self):
        entries = [('barbla', (1230680220, 0), (1230680220, 0), 2050, 3761020, 33188, 1000, 1000, 0, 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391', 0)]
        x = open('test-simple-write-index', 'w+')
        try:
            write_index(x, entries)
        finally:
            x.close()
        x = open('test-simple-write-index', 'r')
        try:
            self.assertEquals(entries, list(read_index(x)))
        finally:
            x.close()


class CommitTreeTests(TestCase):

    def setUp(self):
        super(CommitTreeTests, self).setUp()
        self.store = MemoryObjectStore()

    def test_single_blob(self):
        blob = Blob()
        blob.data = "foo"
        self.store.add_object(blob)
        blobs = [("bla", blob.id, stat.S_IFREG)]
        rootid = commit_tree(self.store, blobs)
        self.assertEquals(rootid, "1a1e80437220f9312e855c37ac4398b68e5c1d50")
        self.assertEquals((stat.S_IFREG, blob.id), self.store[rootid]["bla"])
        self.assertEquals(set([rootid, blob.id]), set(self.store._data.keys()))

    def test_nested(self):
        blob = Blob()
        blob.data = "foo"
        self.store.add_object(blob)
        blobs = [("bla/bar", blob.id, stat.S_IFREG)]
        rootid = commit_tree(self.store, blobs)
        self.assertEquals(rootid, "d92b959b216ad0d044671981196781b3258fa537")
        dirid = self.store[rootid]["bla"][1]
        self.assertEquals(dirid, "c1a1deb9788150829579a8b4efa6311e7b638650")
        self.assertEquals((stat.S_IFDIR, dirid), self.store[rootid]["bla"])
        self.assertEquals((stat.S_IFREG, blob.id), self.store[dirid]["bar"])
        self.assertEquals(set([rootid, dirid, blob.id]), 
                          set(self.store._data.keys()))
