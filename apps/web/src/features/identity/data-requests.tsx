'use client';
import type {DataRequestType} from '@/lib/domain';
import {StatePanel} from '@/components/ui';
import {RequestCopy} from './request-copy';
import {useDataRequestsState} from './use-data-requests-state';
import './data-requests.css';

const labels:Record<DataRequestType,string>={ACCESS:'Xem dữ liệu',EXPORT:'Xuất dữ liệu',CORRECTION:'Chỉnh sửa dữ liệu',DELETE:'Xóa dữ liệu'};
const statuses={PENDING:'Chờ tiếp nhận',IN_REVIEW:'Đang xử lý',COMPLETED:'Đã hoàn tất',REJECTED:'Đã từ chối'};
export function MyDataRequestsFeature(){
 const entry=useDataRequestsState();
 if(!entry)return <StatePanel busy title="Đang tải yêu cầu…"/>;
 const {state:s,controller:c}=entry,locked=s.mutation==='submitting'||s.mutation==='unknown';
 return <div className="data-requests-view">
  <section className="card padded" aria-labelledby="request-form-title">
   <h2 id="request-form-title">Gửi yêu cầu</h2>
   <p className="muted">Nhà trường sẽ xác minh và xử lý theo loại dữ liệu. Yêu cầu xóa không xóa ngay mọi dữ liệu.</p>
   <form className="form-stack" onSubmit={e=>{e.preventDefault();void c.submit();}} aria-busy={s.mutation==='submitting'}>
    <label htmlFor="request-type">Loại yêu cầu<select id="request-type" disabled={locked} value={s.draft.type} onChange={e=>c.setDraftType(e.target.value as DataRequestType)}>{Object.entries(labels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
    <label htmlFor="request-reason">Nội dung bổ sung<textarea id="request-reason" rows={5} maxLength={10000} disabled={locked} value={s.draft.reason} onChange={e=>c.setDraftReason(e.target.value)}/></label>
    {s.mutation==='rejected'&&<div className="notice danger" role="alert"><strong>Chưa gửi được yêu cầu</strong><p>{s.mutationIssue?.message}</p>{s.mutationIssue?.correlationId&&<p>Mã đối soát: <code>{s.mutationIssue.correlationId}</code></p>}<p>Bạn có thể kiểm tra nội dung và chủ động gửi lại.</p></div>}
    {s.mutation==='confirmed'&&s.lastConfirmedRequest&&<p className="notice success" role="status">Đã nhận xác nhận tạo yêu cầu. Mã yêu cầu: <code>{s.lastConfirmedRequest.id}</code>.</p>}
    <button className="button primary" disabled={locked}>{s.mutation==='submitting'?'Đang gửi yêu cầu…':'Gửi yêu cầu'}</button>
   </form>
   {s.mutation==='unknown'&&<section className="notice warning data-request-unknown" role="alert" aria-labelledby="request-unknown-title">
    <h3 id="request-unknown-title">Cần xác minh kết quả gửi</h3>
    <p>Chưa xác định được yêu cầu đã được tạo hay chưa. Không gửi lại để tránh tạo yêu cầu trùng.</p>
    <dl><dt>Loại đã gửi</dt><dd>{s.submittedIntent?labels[s.submittedIntent.type]:labels[s.draft.type]}</dd><dt>Nội dung đã gửi</dt><dd>{s.submittedIntent?.reason||'Không có nội dung bổ sung'}</dd>{s.mutationIssue?.correlationId&&<><dt>Mã đối soát</dt><dd><code>{s.mutationIssue.correlationId}</code></dd></>}</dl>
    <p>Bạn có thể kiểm tra danh sách. Yêu cầu có nội dung giống nhau hoặc danh sách trống chưa đủ để xác nhận kết quả lần gửi này.</p>
    <button className="button" disabled={s.listBusy} onClick={()=>void c.refreshList()}>{s.listBusy?'Đang kiểm tra…':'Kiểm tra lại danh sách'}</button>
    <p>Nếu vẫn chưa rõ, liên hệ quản trị viên nhà trường kèm thông tin đã gửi{s.mutationIssue?.correlationId?' và mã đối soát ở trên':''}. Tải lại trang hoặc đăng nhập lại không xác minh được kết quả; hãy đối soát trước khi gửi lại.</p>
   </section>}
  </section>
  <section className="card padded" aria-labelledby="request-list-title" aria-busy={s.listBusy}>
   <div className="section-heading"><h2 id="request-list-title">Yêu cầu của tôi</h2><button className="button" disabled={s.listBusy||s.mutation==='submitting'} onClick={()=>void c.refreshList()}>Tải lại</button></div>
   {s.listError&&<div className="notice danger" role="alert"><p>{s.listError.message}</p>{s.listError.correlationId&&<p>Mã đối soát danh sách: <code>{s.listError.correlationId}</code></p>}<button className="button" disabled={s.listBusy} onClick={()=>void c.refreshList()}>Thử tải danh sách lại</button></div>}
   {s.listBusy&&<p role="status" className="muted">Đang tải danh sách yêu cầu…</p>}
   {s.items.length?<ul className="item-list">{s.items.map(item=><li key={item.id}><div className="data-request-row-heading"><strong>{labels[item.type]}</strong><span className="status">{statuses[item.status]}</span></div><small>Mã yêu cầu: <code>{item.id}</code></small>{item.reason&&<p className="data-request-content">{item.reason}</p>}{item.resolution_note&&<p className="data-request-content">Phản hồi: {item.resolution_note}</p>}{['ACCESS','EXPORT'].includes(item.type)&&['IN_REVIEW','COMPLETED'].includes(item.status)&&<RequestCopy requestId={item.id}/>}</li>)}</ul>:s.loaded?<p className="muted">Danh sách hiện chưa có yêu cầu nào.{s.mutation==='unknown'?' Kết quả lần gửi vừa rồi vẫn cần được xác minh.':''}</p>:!s.listBusy&&!s.listError?<StatePanel title="Chưa tải được danh sách"/>:null}
   {s.nextCursor&&<button className="button" disabled={s.listBusy} onClick={()=>void c.loadMore()}>Xem thêm</button>}
  </section>
 </div>;
}
