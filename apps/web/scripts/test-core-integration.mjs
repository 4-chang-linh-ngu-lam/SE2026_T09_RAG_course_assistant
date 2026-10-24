import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {randomBytes,randomUUID} from 'node:crypto';
import {access,copyFile,mkdir,mkdtemp,open,readFile,rm,writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';

// Disposable local fixture only. Never accepts an operational URL/database.
const root=fileURLToPath(new URL('../../../',import.meta.url));
const webDirectory=fileURLToPath(new URL('../',import.meta.url));
const nonce=randomBytes(6).toString('hex');
const project=`lumi-smoke-${nonce}`;
const coreImage=`lumi-core-smoke:${nonce}`;
const withDocuments=process.env.CORE_DOCUMENT_TEST==='1';
const documentImage=`lumi-document-smoke:${nonce}`;
const directory=await mkdtemp(join(tmpdir(),'lumi-core-smoke-'));
const envFile=join(directory,'compose.env');
const overrideFile=join(directory,'compose.test.json');
const tlsDirectory=join(directory,'smtp');
const browserFixture=join(directory,'browser-fixture.json');
const compose=['compose','--project-name',project,'--file',join(root,'compose.yaml'),'--file',overrideFile,'--env-file',envFile];
if(withDocuments)compose.push('--profile','document');
let activeChild=null,interrupted=false,cleaning=false,started=false,cleanupSucceeded=false;
let phase='prerequisites',failure=null;
const environment={...process.env};
for(const key of Object.keys(environment))if(key.startsWith('SMTP_'))delete environment[key];
function interrupt(){interrupted=true;if(!cleaning)activeChild?.kill('SIGINT');}
process.on('SIGINT',interrupt);process.on('SIGTERM',interrupt);

async function run(executable,args,logName,env=environment){
  if(interrupted&&!cleaning)throw new Error('Interrupted');
  const log=await open(join(directory,logName),'w',0o600);
  try{
    const code=await new Promise((resolve,reject)=>{
      const child=spawn(executable,args,{cwd:webDirectory,env,stdio:['ignore',log.fd,log.fd],windowsHide:true});
      activeChild=child;
      child.once('error',reject);
      child.once('close',resolve);
    });
    if(code!==0)throw new Error(`${logName}: command exited ${code??'by signal'}`);
    if(interrupted&&!cleaning)throw new Error('Interrupted');
  }finally{activeChild=null;await log.close();}
}
async function freePort(excluded){
  for(let attempt=0;attempt<20;attempt++){
    const server=createServer();
    await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
    const port=server.address().port;
    await new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()));
    if(!excluded.has(port)){excluded.add(port);return port;}
  }
  throw new Error('Could not allocate distinct loopback ports');
}
async function health(origin,path,status,expected){
  const response=await fetch(origin+path,{redirect:'manual',signal:AbortSignal.timeout(15000)});
  assert.equal(response.status,status,'Unexpected health HTTP status');
  const value=await response.json();
  assert.ok(expected(value),'Unexpected health response');
}
async function smoke(script,expected,env){
  const log=script.replace('.ts','.log');
  await run(process.execPath,['--import','tsx',join(webDirectory,'scripts',script)],log,env);
  const lines=(await readFile(join(directory,log),'utf8')).trim().split(/\r?\n/);
  const summary=JSON.parse(lines.at(-1));
  assert.equal(summary.passed,expected,'Smoke group count did not match');
  assert.equal(summary.authenticatedHttp,true);
  assert.equal(summary.fixture,'synthetic');
  if(script==='core-approved-smoke.ts'){assert.equal(summary.adminViewsRendered,3,'Admin views must render actual HTTP receipts');assert.equal(summary.managementViewsRendered,10);assert.equal(summary.coreOperations,46);}
  return expected;
}

try{
  const [major,minor]=process.versions.node.split('.').map(Number);
  assert.ok(major>22||(major===22&&minor>=17),'Node >=22.17.0 required');
  await access(join(webDirectory,'node_modules','tsx','package.json'));
  await run('docker',['version','--format','{{.Server.Version}}'],'docker-version.log');
  const used=new Set();
  const [databasePort,corePort,webPort]=[await freePort(used),await freePort(used),await freePort(used)];
  const core=`http://localhost:${corePort}`,web=`http://localhost:${webPort}`;
  const documentPort=withDocuments?await freePort(used):null;
  const password=randomBytes(32).toString('hex');
  const adminPassword=randomBytes(32).toString('hex');
  const config={
    POSTGRES_DB:'test_http',POSTGRES_USER:'lumi_smoke',POSTGRES_PASSWORD:password,
    POSTGRES_PORT:String(databasePort),CORE_PORT:String(corePort),WEB_PORT:String(webPort),
    DATABASE_URL:`postgresql+psycopg://lumi_smoke:${password}@db:5432/test_http`,
    SECRET_KEY:randomBytes(32).toString('hex'),INTERNAL_SERVICE_SECRET:randomBytes(32).toString('hex'),
    CORE_PROXY_SECRET:randomBytes(32).toString('hex'),COOKIE_SECURE:'false',
    WEB_ORIGIN:web,CORS_ORIGINS:JSON.stringify([web]),NEXT_PUBLIC_DATA_MODE:'live',CORE_IMAGE:coreImage,
    DOCUMENT_EVENTS_SERVICE_SECRET:randomBytes(32).toString('hex'),
    DOCUMENT_INTERNAL_SERVICE_SECRET:randomBytes(32).toString('hex'),
    DOCUMENT_EVENT_READER_SECRET:randomBytes(32).toString('hex'),
    ...(withDocuments?{DOCUMENT_PORT:String(documentPort),DOCUMENT_IMAGE:documentImage,DOCUMENT_DATABASE_URL:`postgresql+psycopg://lumi_document:${randomBytes(32).toString('hex')}@db:5432/test_http`}:{}),
  };
  Object.assign(environment,config);
  await writeFile(envFile,Object.entries(config).map(([key,value])=>`${key}=${value}`).join('\n')+'\n',{mode:0o600});
  await mkdir(tlsDirectory,{mode:0o700});
  await copyFile(new URL('./fixtures/smtp_tls.py',import.meta.url),join(tlsDirectory,'server.py'));
  const tlsProbe="import socket,ssl;c=ssl.create_default_context(cafile='/fixture/ca.crt');s=c.wrap_socket(socket.create_connection(('127.0.0.1',8465),3),server_hostname='mail');s.recv(1024);s.sendall(b'QUIT\\r\\n');s.recv(1024);s.close()";
  await writeFile(overrideFile,JSON.stringify({services:{
    mail:{image:coreImage,build:{context:join(root,'services/core')},command:['python','/fixture/server.py'],
      read_only:true,tmpfs:['/tmp'],cap_drop:['ALL'],security_opt:['no-new-privileges:true'],
      volumes:[{type:'bind',source:tlsDirectory,target:'/fixture'}],
      healthcheck:{test:['CMD','python','-c',tlsProbe],interval:'2s',timeout:'5s',retries:20}},
    core:{environment:{SMTP_HOST:'mail',SMTP_PORT:'8465',SMTP_FROM:'no-reply@fixture.example.com',SMTP_SECURITY:'tls',SSL_CERT_FILE:'/fixture/ca.crt'},
      volumes:[{type:'bind',source:join(tlsDirectory,'ca.crt'),target:'/fixture/ca.crt',read_only:true}],
      depends_on:{mail:{condition:'service_healthy'}}},
  }}),{mode:0o600});
  phase='production Compose build/start';started=true;
  console.log('Building isolated production Core/Web/worker fixture…');
  await run('docker',[...compose,'build'],'compose-build.log');
  await run('docker',['run','--rm','--mount',`type=bind,source=${tlsDirectory},target=/fixture`,coreImage,
    'openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout','/fixture/mail.key','-out','/fixture/ca.crt','-days','1',
    '-subj','/CN=mail','-addext','subjectAltName=DNS:mail'],'test-ca.log');
  await run('docker',[...compose,'up','-d','--wait','--wait-timeout','180'],'compose-up.log');
  await run('docker',[...compose,'exec','-T','core','id','-u'],'runtime-user.log');
  assert.notEqual((await readFile(join(directory,'runtime-user.log'),'utf8')).trim(),'0');
  await run('docker',[...compose,'exec','-T','core','python','-c',"from pathlib import Path;import app;assert 'site-packages' in str(Path(app.__file__))"],'installed-package.log');
  await run('docker',[...compose,'exec','-T','core','python','-m','alembic','check'],'migration-check.log');
  await health(core,'/health/ready',200,value=>value.status==='ready'&&value.db==='connected');
  if(withDocuments){
    await health(`http://localhost:${documentPort}`,'/health/ready',200,value=>value.status==='ready');
    await run('docker',[...compose,'exec','-T','document','python','-m','alembic','check'],'document-migration-check.log');
    await run('docker',[...compose,'exec','-T','document','id','-u'],'document-runtime-user.log');
    assert.notEqual((await readFile(join(directory,'document-runtime-user.log'),'utf8')).trim(),'0');
  }
  console.log('PASS production Compose, non-root installed package and migration');
  phase='guarded synthetic seed';
  const seedEnv={...environment,CORE_SEED_ADMIN_PASSWORD:adminPassword};
  const school=randomUUID();
  const seedArgs=['run','--rm','--network',`${project}_default`,'-e','DATABASE_URL','-e','CORE_SEED_ADMIN_PASSWORD',coreImage,
    'python','-m','app.maintenance','seed-dev','--environment','test','--expected-database','test_http',
    '--school-id',school,'--school-name','Lumi Synthetic HTTP Fixture'];
  for(const [log,created]of [['seed-first.log',true],['seed-repeat.log',false]]){
    await run('docker',seedArgs,log,seedEnv);
    assert.equal(JSON.parse(await readFile(join(directory,log),'utf8')).created,created,'Unexpected seed result');
  }
  console.log('PASS guarded seed and repeat safety');
  const smokeEnv={...environment,CORE_SECURITY_TEST_MODE:'synthetic',CORE_SECURITY_WEB_URL:web,
    CORE_SECURITY_API_URL:core,CORE_SECURITY_ADMIN_EMAIL:'admin@seed.example.com',CORE_SECURITY_ADMIN_PASSWORD:adminPassword,
    CORE_SECURITY_MAIL_PATH:join(tlsDirectory,'messages.jsonl'),
    ...(process.env.CORE_BROWSER_EXECUTABLE||withDocuments?{CORE_BROWSER_FIXTURE_PATH:browserFixture,CORE_BROWSER_ARTIFACT_DIR:directory}:{}),
    ...(withDocuments?{DOCUMENT_SECURITY_API_URL:`http://localhost:${documentPort}`}:{})};
  phase='46 approved Core operations HTTP';
  const coreGroups=await smoke('core-approved-smoke.ts',7,smokeEnv);
  console.log('PASS 46 approved Core operations across 7 HTTP groups, including synthetic TLS email');
  phase='Notifications HTTP';
  const notificationGroups=await smoke('core-notification-smoke.ts',7,smokeEnv);
  console.log('PASS 7 Notifications HTTP groups');
  let documentGroups=0;
  if(withDocuments){
    phase='Document fullstack HTTP';documentGroups=await smoke('document-approved-smoke.ts',6,smokeEnv);
    console.log('PASS 6 Document fullstack HTTP groups with current Core permissions and notification delivery');
  }
  let browserGroups=0,documentBrowserGroups=0,browserFailed=false;
  if(process.env.CORE_BROWSER_EXECUTABLE){
    phase='real browser interaction';
    try{browserGroups=await smoke('core-browser-smoke.ts',10,smokeEnv);console.log('PASS 10 real browser interaction groups (isolated Chrome profile)');}
    catch{browserFailed=true;console.error('FAIL browser interaction; continuing independent HTTP/recovery checks');}
    if(withDocuments){
      phase='Document browser interaction';
      try{documentBrowserGroups=await smoke('document-browser-smoke.ts',6,smokeEnv);console.log('PASS 6 Document browser interaction groups');}
      catch{browserFailed=true;console.error('FAIL Document browser interaction; continuing independent HTTP/recovery checks');}
    }
  }
  phase='Identity/security HTTP';
  // Keep failed-login rate-limit checks last so they do not affect provisioning.
  const securityGroups=await smoke('core-security-smoke.ts',8,smokeEnv);
  console.log('PASS 8 Identity/security HTTP groups');
  phase='database outage/recovery';
  await run('docker',[...compose,'stop','db'],'database-stop.log');
  await health(core,'/health/ready',503,value=>value.error?.code==='SERVICE_UNAVAILABLE');
  await health(core,'/health/live',200,value=>value.status==='live');
  await run('docker',[...compose,'up','-d','--wait','--wait-timeout','90','db'],'database-start.log');
  let recovered=false;
  for(let attempt=0;attempt<20;attempt++){
    try{await health(core,'/health/ready',200,value=>value.status==='ready');recovered=true;break;}
    catch{await delay(500);}
  }
  assert.ok(recovered,'Readiness did not recover');
  console.log('PASS DB outage: ready503/live200; recovery ready200');
  await writeFile(join(directory,'summary.json'),JSON.stringify({coreGroups,coreOperations:46,adminViewsRendered:3,managementViewsRendered:10,notificationGroups,securityGroups,syntheticTlsSmtp:true,
    productionCompose:true,nonRoot:true,installedPackage:true,migrationCheck:true,seedRepeat:true,documentGroups,
    dbOutageRecovery:true,syntheticOnly:true,browserGroups,documentBrowserGroups,browserInteraction:browserGroups>0,realSmtpVerified:false},null,2),{mode:0o600});
  if(browserFailed){phase='real browser interaction';throw new Error('Browser acceptance failed');}
}catch(error){
  failure=error;
  // Assertions may include secrets in their detail. Print only phase and a fixed class.
  console.error(`FAIL phase=${phase}; type=${error?.name??'Error'}`);
}finally{
  cleaning=true;
  try{
    assert.match(project,/^lumi-smoke-[a-f0-9]{12}$/);
    if(started)await run('docker',[...compose,'down','--volumes','--remove-orphans'],'compose-cleanup.log');
    cleanupSucceeded=true;
  }catch{console.error('FAIL isolated fixture cleanup; inspect private compose-cleanup.log');}
  finally{
    await rm(envFile,{force:true});
    await rm(browserFixture,{force:true});
    for(const file of ['mail.key','ca.crt','messages.jsonl'])await rm(join(tlsDirectory,file),{force:true});
    process.removeListener('SIGINT',interrupt);process.removeListener('SIGTERM',interrupt);
  }
}
console.log(`Private logs and aggregate evidence: ${directory}`);
if(failure||!cleanupSucceeded||interrupted)process.exitCode=1;
else console.log('PASS isolated Web–Core integration; test containers/volume and credential file removed.');
