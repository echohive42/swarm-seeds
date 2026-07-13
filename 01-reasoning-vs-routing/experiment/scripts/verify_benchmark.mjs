import fs from "node:fs";
const root=new URL("../",import.meta.url),m=JSON.parse(fs.readFileSync(new URL("benchmark/manifest.json",root),"utf8"));
const primes=[2n,3n,5n,7n,11n,13n,17n,19n,23n,29n,31n,37n,41n];
const cat=[];for(let n=0n;n<13n;n++){let v=1n;for(let k=1n;k<=n;k++)v=v*(n+k)/k;cat.push(v/(n+1n));}
let s=0n;const primeSquares=primes.map(p=>s+=p*p);
let d=1n;const d03=[d];for(let n=2;n<=13;n++){d=BigInt(n+1)*d+(n%2===0?1n:-1n);d03.push(d);}
let fact=1n;const d04=[];for(let k=1n;k<=7n;k++){fact*=k;d04.push(k*k,fact);}
const zig=[[1n]],euler=[1n];for(let n=1;n<=12;n++){const row=[0n];for(let k=1;k<=n;k++)row.push(row[k-1]+zig[n-1][n-k]);zig.push(row);euler.push(row[n]);}
const invol=[1n,1n];for(let n=2;n<=12;n++)invol.push(invol[n-1]+BigInt(n-1)*invol[n-2]);
const central=[];for(let n=0;n<=12;n++){let coeff=[1n];for(let j=0;j<n;j++){const next=Array(coeff.length+2).fill(0n);coeff.forEach((v,i)=>{next[i]+=v;next[i+1]+=v;next[i+2]+=v;});coeff=next;}central.push(coeff[n]);}
const mot=[1n,1n];for(let n=2;n<=12;n++)mot.push(((2n*BigInt(n)+1n)*mot[n-1]+(3n*BigInt(n)-3n)*mot[n-2])/(BigInt(n)+2n));
s=0n;const f05=primes.map(p=>s+=p**4n);
let a=2n;const f06=[a];for(let n=2;n<=13;n++){a=BigInt(n)*a+(n%2===0?1n:-1n)*primes[n-1];f06.push(a);}
const f07=[];for(let k=0;k<7;k++)f07.push(cat[k],3n**BigInt(k+1));
const f08=[];for(let n=3;n<=15;n++)f08.push((3n**BigInt(n)-3n*2n**BigInt(n)+3n)/6n);
const f09=primes.map((p,i)=>BigInt(i+1)**5n+p);
const composites=[4n,6n,8n,9n,10n,12n,14n,15n,16n,18n,20n,21n,22n];s=0n;const f10=composites.map(x=>s+=x**3n);
a=3n;const f11=[a];for(let n=2;n<=13;n++){a=2n*a+BigInt(n*n)+(n%2===0?1n:-1n);f11.push(a);}
const f12=[];for(let n=1;n<=13;n++)f12.push(n===1?1n:BigInt(n)**BigInt(n-2));
const expected={D01:cat,D02:primeSquares,D03:d03,D04:d04,F01:euler,F02:invol,F03:central,F04:mot,F05:f05,F06:f06,F07:f07,F08:f08,F09:f09,F10:f10,F11:f11,F12:f12};
let ok=true;for(const c of [...m.development,...m.final]){const got=[...c.prefix,...c.next].map(BigInt),want=expected[c.id];const same=got.length===13&&got.every((v,i)=>v===want[i]);console.log(JSON.stringify({id:c.id,verified:same}));if(!same)ok=false;}if(!ok)process.exit(1);
