'use client';
import {useEffect,useRef,useState} from 'react';
export type AssessmentClock={serverMs:number;receivedAt:number};
export const createAssessmentClock=(serverNow:string,receivedAt=performance.now()):AssessmentClock=>({serverMs:Date.parse(serverNow),receivedAt});
export function assessmentRemaining(endsAt:string,serverOffset:number,now:number):number {return Math.max(0,Date.parse(endsAt)-now-serverOffset);}
export function assessmentClockRemaining(endsAt:string,clock:AssessmentClock,now=performance.now()):number {
 return assessmentRemaining(endsAt,0,clock.serverMs+Math.max(0,now-clock.receivedAt));
}
/** Monotonic time and a leaf update keep wall-clock changes and 1Hz work out of the exam form. */
export function AssessmentCountdown({endsAt,clock,onExpire}:{endsAt:string;clock:AssessmentClock;onExpire():void}) {
 const [now,setNow]=useState(()=>performance.now());const notified=useRef(false);
 const remaining=assessmentClockRemaining(endsAt,clock,now);
 useEffect(()=>{const tick=()=>setNow(performance.now());tick();const timer=setInterval(tick,1000);return()=>clearInterval(timer);},[endsAt,clock]);
 useEffect(()=>{if(remaining>0)notified.current=false;else if(!notified.current){notified.current=true;onExpire();}},[remaining,onExpire]);
 return <span className="as-timer" role="timer" aria-label="Thời gian còn lại">{Math.floor(remaining/60000)}:{String(Math.floor(remaining/1000)%60).padStart(2,'0')}</span>;
}
