===================================
oslo.versionedobjects
===================================

oslo.versionedobjects library deals with DB schema being at different versions
than the code expects, allowing services to be operated safely during upgrades.
It enables DB independent schema by providing an abstraction layer, which
allows us to support SQL and NoSQL Databases. oslo.versionedobjects is also
used in RPC APIs, to ensure upgrades happen without spreading version dependent
code across different services and projects.

* Free software: Apache license
* Documentation: http://docs.openstack.org/developer/oslo.versionedobjects
* Source: http://git.openstack.org/cgit/openstack/oslo.versionedobjects
* Bugs: http://bugs.launchpad.net/oslo.versionedobjects
