import time
from utils import grep
from utils import require_user
from pyroute2 import NDB
from pyroute2 import IPRoute
from pyroute2.common import uifname
from pyroute2.common import basestring
from pyroute2.ndb import main
from pyroute2.ndb.main import Report


class TestBase(object):

    db_provider = 'sqlite3'
    db_spec = ':memory:'

    def link_wait(self, ifname):
        with IPRoute() as ipr:
            for _ in range(5):
                try:
                    return ipr.link_lookup(ifname=ifname)[0]
                except:
                    time.sleep(0.1)
            raise Exception('link setup error')

    def create_interfaces(self):
        # dummy interface
        if_dummy = uifname()
        if_vlan_stag = uifname()
        if_vlan_ctag = uifname()
        if_bridge = uifname()
        if_port = uifname()
        ret = []

        with IPRoute() as ipr:

            ipr.link('add',
                     ifname=if_dummy,
                     kind='dummy')
            ret.append(self.link_wait(if_dummy))

            ipr.link('add',
                     ifname=if_vlan_stag,
                     link=ret[-1],
                     vlan_id=101,
                     vlan_protocol=0x88a8,
                     kind='vlan')
            ret.append(self.link_wait(if_vlan_stag))

            ipr.link('add',
                     ifname=if_vlan_ctag,
                     link=ret[-1],
                     vlan_id=1001,
                     vlan_protocol=0x8100,
                     kind='vlan')
            ret.append(self.link_wait(if_vlan_ctag))

            ipr.link('add',
                     ifname=if_port,
                     kind='dummy')
            ret.append(self.link_wait(if_port))

            ipr.link('add',
                     ifname=if_bridge,
                     kind='bridge')
            ret.append(self.link_wait(if_bridge))
            ipr.link('set', index=ret[-2], master=ret[-1])
            return ret

    def setup(self):
        require_user('root')
        self.if_simple = None
        self.interfaces = self.create_interfaces()
        self.ndb = NDB(db_provider=self.db_provider,
                       db_spec=self.db_spec)
        self.interfaces += self.create_interfaces()

    def teardown(self):
        with IPRoute() as ipr:
            for link in reversed(self.interfaces):
                ipr.link('del', index=link)
        self.ndb.close()

    def fetch(self, request, values=[]):
        with self.ndb.schema.db_lock:
            return (self
                    .ndb
                    .schema
                    .execute(request, values)
                    .fetchall())


class TestRollback(TestBase):

    def setup(self):
        require_user('root')
        self.ndb = NDB(db_provider=self.db_provider,
                       db_spec=self.db_spec)

    def test_simple_deps(self):
        with IPRoute() as ipr:
            self.interfaces = []
            #
            # simple dummy interface with one address and
            # one dependent route
            #
            self.if_simple = uifname()
            ipr.link('add',
                     ifname=self.if_simple,
                     kind='dummy')
            self.interfaces.append(self.link_wait(self.if_simple))
            ipr.link('set',
                     index=self.interfaces[-1],
                     state='up')
            ipr.addr('add',
                     index=self.interfaces[-1],
                     address='172.16.172.16',
                     prefixlen=24)
            ipr.route('add',
                      dst='172.16.127.0',
                      dst_len=24,
                      gateway='172.16.172.17')

        iface = self.ndb.interfaces[self.if_simple]
        # check everything is in place
        assert grep('ip link show', pattern=self.if_simple)
        assert grep('ip route show', pattern=self.if_simple)
        assert grep('ip route show', pattern='172.16.127.*172.16.172.17')

        # remove the interface
        iface.remove()
        iface.commit()

        # check there is no interface, no route
        assert not grep('ip link show', pattern=self.if_simple)
        assert not grep('ip route show', pattern=self.if_simple)
        assert not grep('ip route show', pattern='172.16.127.*172.16.172.17')

        # revert the changes using the implicit last_save
        iface.rollback()
        assert grep('ip link show', pattern=self.if_simple)
        assert grep('ip route show', pattern=self.if_simple)
        assert grep('ip route show', pattern='172.16.127.*172.16.172.17')

    def test_bridge_deps(self):
        with IPRoute() as ipr:
            self.interfaces = []
            self.if_br0 = uifname()
            ipr.link('add',
                     ifname=self.if_br0,
                     kind='bridge')
            self.interfaces.append(self.link_wait(self.if_br0))
            ipr.link('set',
                     index=self.interfaces[-1],
                     state='up')
            ipr.addr('add',
                     index=self.interfaces[-1],
                     address='172.16.173.16',
                     prefixlen=24)
            ipr.addr('add',
                     index=self.interfaces[-1],
                     address='172.16.173.17',
                     prefixlen=24)
            ipr.route('add',
                      dst='172.16.128.0',
                      dst_len=24,
                      gateway='172.16.173.18')
            self.if_br0p0 = uifname()
            ipr.link('add',
                     ifname=self.if_br0p0,
                     kind='dummy')
            self.interfaces.append(self.link_wait(self.if_br0p0))
            ipr.link('set',
                     index=self.interfaces[-1],
                     state='up',
                     master=self.interfaces[-2])
            self.if_br0p1 = uifname()
            ipr.link('add',
                     ifname=self.if_br0p1,
                     kind='dummy')
            self.interfaces.append(self.link_wait(self.if_br0p1))
            ipr.link('set',
                     index=self.interfaces[-1],
                     state='up',
                     master=self.interfaces[-3])
        iface = self.ndb.interfaces[self.if_br0]
        # check everything is in place
        assert grep('ip link show', pattern=self.if_br0)
        assert grep('ip link show', pattern=self.if_br0p0)
        assert grep('ip link show', pattern=self.if_br0p1)
        assert grep('ip addr show', pattern='172.16.173.16')
        assert grep('ip addr show', pattern='172.16.173.17')
        assert grep('ip route show', pattern=self.if_br0)
        assert grep('ip route show', pattern='172.16.128.*172.16.173.18')
        # import rpdb2
        # rpdb2.start_embedded_debugger("bala")

        # remove the interface
        iface.remove()
        iface.commit()

        # check there is no interface, no route
        assert not grep('ip link show', pattern=self.if_br0)
        assert grep('ip link show', pattern=self.if_br0p0)
        assert grep('ip link show', pattern=self.if_br0p1)
        assert not grep('ip addr show', pattern='172.16.173.16')
        assert not grep('ip addr show', pattern='172.16.173.17')
        assert not grep('ip route show', pattern=self.if_br0)
        assert not grep('ip route show', pattern='172.16.128.*172.16.173.18')

        # revert the changes using the implicit last_save
        iface.rollback()
        assert grep('ip link show', pattern=self.if_br0)
        assert grep('ip link show', pattern=self.if_br0p0)
        assert grep('ip link show', pattern=self.if_br0p1)
        assert grep('ip addr show', pattern='172.16.173.16')
        assert grep('ip addr show', pattern='172.16.173.17')
        assert grep('ip route show', pattern=self.if_br0)
        assert grep('ip route show', pattern='172.16.128.*172.16.173.18')


class TestSchema(TestBase):

    def test_basic(self):
        assert len(set(self.interfaces) -
                   set([x[0] for x in
                        self.fetch('select f_index from interfaces')])) == 0

    def test_vlan_interfaces(self):
        assert len(self.fetch('select * from vlan')) >= 4

    def test_bridge_interfaces(self):
        assert len(self.fetch('select * from bridge')) >= 2


class TestReports(TestBase):

    def test_types(self):
        main.MAX_REPORT_LINES = 1
        # check for the report type here
        assert isinstance(self.ndb.interfaces.summary(), Report)
        # repr must be a string
        assert isinstance(repr(self.ndb.interfaces.summary()), basestring)
        # header + MAX_REPORT_LINES + (...)
        assert len(repr(self.ndb.interfaces.summary()).split('\n')) == 3

    def test_dump(self):
        for record in self.ndb.addresses.dump():
            assert isinstance(record, tuple)

    def test_csv(self):
        l = 0

        for record in self.ndb.routes.dump():
            if l == 0:
                l = len(record)
            else:
                assert len(record) == l

        for record in self.ndb.routes.csv():
            assert len(record.split(',')) == l
