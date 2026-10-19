import type { AssessmentAnswers, AssessmentAttempt } from '@/lib/assessment';

// One request at a time. An ambiguous acknowledgement blocks writes until a read
// reconciles authority; neither submit nor disposal can turn it into saved data.
export class AssessmentAnswerSaver {
 private queued:AssessmentAnswers|null=null;
 private active:Promise<void>|null=null;
 private failed:unknown=null;
 private disposed=false;
 constructor(private revision:number,private write:(answers:AssessmentAnswers,revision:number)=>Promise<AssessmentAttempt>,private ack:(attempt:AssessmentAttempt,pending:boolean)=>void){}
 enqueue(answers:AssessmentAnswers):void{if(this.disposed)throw new Error('Lượt làm đã đóng.');this.queued=structuredClone(answers);if(!this.active&&!this.failed)this.start();}
 private start(){this.active=this.run().finally(()=>{this.active=null;});}
 private async run(){while(this.queued&&!this.disposed&&!this.failed){const snapshot=this.queued;this.queued=null;try{const a=await this.write(snapshot,this.revision);if(this.disposed)throw new Error('Lượt làm đã đóng.');this.revision=a.savedRevision;this.ack(a,!!this.queued);}catch(e){this.failed=e;if(!this.queued)this.queued=snapshot;}}}
 async flush():Promise<void>{if(this.disposed)throw new Error('Lượt làm đã đóng.');while(this.active){await this.active;}if(this.failed)throw this.failed;if(this.disposed)throw new Error('Lượt làm đã đóng.');if(this.queued){this.start();return this.flush();}}
 reconcile(revision:number):void{if(this.active)throw new Error('Đang chờ phản hồi lưu.');this.revision=revision;this.failed=null;}
 get currentRevision(){return this.revision;}
 dispose(){this.disposed=true;this.queued=null;}
}
