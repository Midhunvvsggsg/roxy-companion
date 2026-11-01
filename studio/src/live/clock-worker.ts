// A worker clock keeps relay updates and health checks independent of page painting.
setInterval(() => self.postMessage(null), 1000 / 30);
