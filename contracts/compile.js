// Compiles TrueMarkRegistry.sol with solc-js and writes build/TrueMarkRegistry.json (abi + bytecode).
// The Python app only needs that JSON file, so you only run this if you change the contract.
//   cd contracts && npm install && npm run compile
const fs = require("fs");
const path = require("path");
const solc = require("solc");

const file = "TrueMarkRegistry.sol";
const source = fs.readFileSync(path.join(__dirname, file), "utf8");

const input = {
  language: "Solidity",
  sources: { [file]: { content: source } },
  settings: {
    optimizer: { enabled: true, runs: 200 },
    evmVersion: "paris", // widest compatibility (Sepolia, Amoy, most L2s)
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const out = JSON.parse(solc.compile(JSON.stringify(input)));
const errors = (out.errors || []).filter((e) => e.severity === "error");
if (errors.length) {
  console.error(errors.map((e) => e.formattedMessage).join("\n"));
  process.exit(1);
}
(out.errors || []).forEach((e) => console.warn(e.formattedMessage));

const c = out.contracts[file].TrueMarkRegistry;
const artifact = {
  contractName: "TrueMarkRegistry",
  compiler: "solc " + solc.version(),
  abi: c.abi,
  bytecode: "0x" + c.evm.bytecode.object,
};
fs.mkdirSync(path.join(__dirname, "build"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "build", "TrueMarkRegistry.json"), JSON.stringify(artifact, null, 2) + "\n");
console.log("Wrote build/TrueMarkRegistry.json (" + (artifact.bytecode.length - 2) / 2 + " bytes of bytecode)");
