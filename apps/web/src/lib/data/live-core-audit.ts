import type {CoreApiPort,CoreAudit} from '../api/core-contract';
import type {IntelligenceAuditRecord,IntelligencePort} from '../intelligence';
import type {createLiveCoreSession} from './live-identity';
import {ApiError} from '../api/errors';
import {allCorePages} from './live-classroom-social';
import {createUnavailableIntelligencePort} from './intelligence-unavailable';

const reasons:Record<string,string>={ADMIN_INTERVENTION:'Can thiệp quản trị',USER_REQUEST:'Theo yêu cầu người dùng',POLICY_VIOLATION:'Vi phạm chính sách'};
export function coreAuditRecord(row:CoreAudit):IntelligenceAuditRecord{
  const reason=row.metadata_json.reason_code;
  return {id:row.id,actorId:row.actor_id??'',actorName:row.actor_id??'Chưa có thông tin người thực hiện',action:row.action,
    resourceType:row.target_type,resourceId:row.target_id,reason:typeof reason==='string'&&Object.hasOwn(reasons,reason)?reasons[reason]:'Chưa có lý do được công bố',at:row.occurred_at};
}

// Audit belongs to Core.Administration even though the existing screen shares
// the frontend Intelligence port. No other Intelligence operation is enabled.
export function createLiveCoreAudit(session:Pick<ReturnType<typeof createLiveCoreSession>,'getActorId'>,api:CoreApiPort):IntelligencePort{
  const unavailable=createUnavailableIntelligencePort();
  return {...unavailable,async load(routeId,params,filter,signal){
    if(routeId!=='a.audit')return unavailable.load(routeId,params,filter,signal);
    const actor=session.getActorId();
    if(!actor)throw new ApiError('SESSION_UNCONFIRMED','Cần xác nhận tài khoản trước khi tiếp tục.',401);
    const bounded=signal?AbortSignal.any([signal,AbortSignal.timeout(15000)]):AbortSignal.timeout(15000);
    const check=()=>{if(session.getActorId()!==actor)throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi.',401);if(bounded.aborted)throw new ApiError('CONNECTION_ERROR','Đã dừng tải nhật ký.',0);};
    const rows=await allCorePages(cursor=>{check();return api.request('auditEvents',{cursor,limit:100,signal:bounded});},bounded);
    check();return {kind:'audit',items:rows.map(coreAuditRecord)};
  }};
}
