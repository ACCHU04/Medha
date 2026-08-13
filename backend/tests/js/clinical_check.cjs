"use strict";
/* NEWS2-5 + SIRS parity harness: runs the browser clinical.js scoring over a
 * scenario of vital observations and echoes the results as JSON for the
 * Python test to compare against app.services.clinical. */

const path = require("path");
const fs = require("fs");

const clinicalJsDir = process.argv[2];
const scenarioPath = process.argv[3];

const { computeNews2, computeSirs } = require(path.join(clinicalJsDir, "clinical.js"));

const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
const results = [];
for (const entry of scenario.cases) {
  results.push({
    news2: computeNews2(entry.vital),
    sirs: computeSirs(entry.vital, entry.suspected_infection),
  });
}
process.stdout.write(JSON.stringify({ results }));
