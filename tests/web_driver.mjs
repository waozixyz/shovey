// Install the private test driver before even a cached runtime can start.
export const driverSetup = `
  let testModule;
  Object.defineProperty(globalThis, 'Module', {
    configurable: true,
    get() { return testModule; },
    set(value) {
      testModule = value;
      if (!value || value.privateDriverPrepared) return;
      value.privateDriverPrepared = true;
      const previous = value.preRun || [];
      value.preRun = [function() {
        ENV.KRYON_TEST_DRIVER = '/tmp/test-driver';
        value.FS.mkdirTree('/tmp/test-driver');
      }, ...(Array.isArray(previous) ? previous : [previous])];
    }
  });
`;
