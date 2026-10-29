// Load before tests/build; injected HTTP/fetch substitutes still work.
const net = require('node:net');
const denied = () => { throw new Error('Offline checks forbid real network connections'); };
net.Socket.prototype.connect = denied;
net.Server.prototype.listen = denied;
require('node:tls').connect = denied;
require('node:dns').lookup = denied;
require('node:dns').resolve = denied;
require('node:module').syncBuiltinESMExports();
