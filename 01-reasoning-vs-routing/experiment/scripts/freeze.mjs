import fs from "node:fs";import path from "node:path";import crypto from "node:crypto";import{fileURLToPath}from"node:url";
const root=path.resolve(fileURLToPath(new URL("../",import.meta.url))),files=["PROTOCOL.md","benchmark/manifest.json","scripts/compose_prompt.mjs","scripts/verify_benchmark.mjs",...fs.readdirSync(path.join(root,"prompts")).sort().map(x=>"prompts/"+x)];
const hashes={};for(const f of files)hashes[f]=crypto.createHash("sha256").update(fs.readFileSync(path.join(root,f))).digest("hex");
const freeze={protocol_version:"1.0.0",frozen_at:new Date().toISOString(),model:"gpt-5.6-luna",reasoning_arms:["low","medium"],immutable_files:hashes,final_thread_count_before_freeze:fs.readdirSync(path.join(root,"raw/final")).length};
fs.writeFileSync(path.join(root,"freeze_manifest.json"),JSON.stringify(freeze,null,2)+"\n");console.log(JSON.stringify(freeze,null,2));
