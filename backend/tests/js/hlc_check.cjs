"use strict";
const path = require("path");
const fs = require("fs");

const appJsDir = process.argv[2];
const scenarioPath = process.argv[3];

const { HlcClock, hlcCmp } = require(path.join(appJsDir, "app.js"));

const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
const clock = new HlcClock(scenario.device_id, () => scenario.wall.shift());

const out = [];
for (const call of scenario.calls) {
  out.push(clock.now(call.received));
}

let guardOk = false;
try {
  new HlcClock("short");
} catch (err) {
  guardOk = /36/.test(String(err.message));
}

const order = hlcCmp(scenario.order_a, scenario.order_b);
process.stdout.write(JSON.stringify({ out, order, guardOk }));
