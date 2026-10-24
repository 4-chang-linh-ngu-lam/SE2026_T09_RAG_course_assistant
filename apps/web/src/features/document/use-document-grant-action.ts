'use client';
import {useEffect, useRef, useState} from 'react';
import {useSession} from '@/components/session-provider';
import {adapter} from '@/lib/data';
import {ApiError, errorMessage} from '@/lib/api/errors';
import {draftStore} from '@/lib/draft-store';
import {documentGrantConfirmed, type DocumentGrantChange} from '@/lib/document-sharing';

export function useDocumentGrantAction() {
  const {user}=useSession();
  const key=`${user?.id}:document-grant-unknown`;
  const [,render]=useState(0);
  const [busy,setBusy]=useState(false),[error,setError]=useState<string|null>(null),[message,setMessage]=useState<string|null>(null);
  const inFlight=useRef(false),scope=useRef(0);
  const original=useRef<{key:string;epoch:number;work:()=>Promise<void>;confirmed:()=>void}|null>(null);
  useEffect(()=>{++scope.current;return()=>{++scope.current;};},[key]);
  const unknown=busy?null:draftStore.get<DocumentGrantChange>(key);
  async function run(change:DocumentGrantChange, work:()=>Promise<void>, confirmed:()=>void) {
    if(inFlight.current||draftStore.get(key))return;
    inFlight.current=true;setBusy(true);setError(null);setMessage(null);
    const generation=scope.current,epoch=draftStore.epoch;
    original.current={key,epoch,work,confirmed};
    // Retain a pending target across unmount; navigation cannot silently enable retry.
    draftStore.set(key,change);
    try {
      await work();
      if(draftStore.epoch===epoch)draftStore.remove(key);
      if(scope.current===generation){setMessage('Đã xác nhận cập nhật quyền chia sẻ.');confirmed();}
    } catch(e) {
      if(e instanceof ApiError&&e.outcome!=='unknown'&&draftStore.epoch===epoch)draftStore.remove(key);
      if(scope.current===generation)setError(errorMessage(e));
    } finally {
      inFlight.current=false;
      if(scope.current===generation){setBusy(false);render(n=>n+1);}
    }
  }
  async function reconcile(confirmed:()=>void) {
    const change=draftStore.get<DocumentGrantChange>(key);
    if(inFlight.current)return;
    if(!change){setError(null);render(n=>n+1);confirmed();return;}
    inFlight.current=true;setBusy(true);setError(null);setMessage(null);
    const generation=scope.current,epoch=draftStore.epoch;
    try {
      const data=await adapter.workspace.load(change.classRoute?'t.documents':'t.libraryDocument',change.classRoute?{classId:change.classRoute}:{documentId:change.documentId});
      if(scope.current!==generation||draftStore.epoch!==epoch)return;
      if(documentGrantConfirmed(change,data)){draftStore.remove(key);setMessage('Đã đối soát: quyền chia sẻ khớp với thay đổi đã gửi.');confirmed();}
      else setError('Chưa có bằng chứng xác nhận kết quả. Không gửi lại; kiểm tra lại sau hoặc liên hệ quản trị viên để xác minh.');
    }catch(e){if(scope.current===generation)setError(errorMessage(e));}
    finally{inFlight.current=false;if(scope.current===generation){setBusy(false);render(n=>n+1);}}
  }
  async function retryOriginal(){
    const saved=original.current;
    if(inFlight.current||!draftStore.get(key)||!saved||saved.key!==key||saved.epoch!==draftStore.epoch)return;
    const generation=scope.current;inFlight.current=true;setBusy(true);setError(null);
    try{await saved.work();if(saved.epoch===draftStore.epoch)draftStore.remove(key);if(scope.current===generation){setMessage('Đã xác nhận đúng yêu cầu chia sẻ đã gửi.');saved.confirmed();}}
    catch(error){if(scope.current===generation)setError(errorMessage(error));}
    finally{inFlight.current=false;if(scope.current===generation){setBusy(false);render(n=>n+1);}}
  }
  return {busy,unknown,error,message,run,reconcile,retryOriginal,canRetryOriginal:Boolean(unknown&&original.current?.key===key&&original.current.epoch===draftStore.epoch),clearError:()=>{setError(null);setMessage(null);}};
}
