import fs from "node:fs";import path from "node:path";import{fileURLToPath}from"node:url";
const root=path.resolve(fileURLToPath(new URL("../",import.meta.url))),split=process.argv[2],stage=process.argv[3],role=process.argv[4]??"",packetPath=process.argv[5]??"";
const read=f=>fs.readFileSync(path.join(root,f),"utf8").trim(),m=JSON.parse(read("benchmark/manifest.json")),cases=m[split].map(({id,prefix})=>({id,prefix}));
let roleFile,schemaFile,packetLabel="";
if(stage==="independent"){roleFile="prompts/INDEPENDENT_SOLVER.txt";schemaFile="prompts/SCHEMA_SOLVER.txt";}
else if(stage==="proposer"){roleFile=`prompts/PROPOSER_${role}.txt`;schemaFile="prompts/SCHEMA_SOLVER.txt";}
else if(stage==="critic"){roleFile=role==="exactness"?"prompts/CRITIC_EXACTNESS.txt":"prompts/CRITIC_SIMPLICITY.txt";schemaFile="prompts/SCHEMA_CRITIC.txt";packetLabel="ANONYMOUS SAME-ARM PROPOSALS";}
else if(stage==="verifier"){roleFile=role==="rule"?"prompts/VERIFIER_RULE.txt":"prompts/VERIFIER_ARITHMETIC.txt";schemaFile="prompts/SCHEMA_VERIFIER.txt";packetLabel="SAME-ARM PROPOSALS AND CRITIQUES";}
else if(stage==="judge"){roleFile="prompts/JUDGE.txt";schemaFile="prompts/SCHEMA_JUDGE.txt";packetLabel="SAME-ARM PROPOSALS, CRITIQUES, AND VERIFICATIONS";}
else throw Error("unknown stage");
let out=[read("prompts/COMMON_PREFIX.txt"),read(roleFile),"CASES\n"+JSON.stringify(cases),read(schemaFile)];
if(packetPath)out.splice(3,0,packetLabel+"\n"+read(packetPath));
process.stdout.write(out.join("\n\n")+"\n");
