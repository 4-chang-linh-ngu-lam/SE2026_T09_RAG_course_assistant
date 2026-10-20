import type {DocumentCapabilityPolicy} from './domain';
export type UploadFile = {name:string;size:number;type:string};
export function documentFileError(file:UploadFile|null|undefined, policy?:DocumentCapabilityPolicy):string|null {
  if(!policy)return 'Chính sách tải lên tài liệu chưa sẵn sàng trên hệ thống.';
  if(!file)return 'Vui lòng chọn tệp tin tải lên.';
  if(!Number.isFinite(file.size)||file.size<=0)return 'Tệp tin không được rỗng (0 bytes). Vui lòng chọn tệp có nội dung.';
  const dot=file.name.lastIndexOf('.');
  const ext=dot>=0?file.name.slice(dot).toLowerCase():'';
  if(!policy.allowedExtensions.map(e=>e.toLowerCase()).includes(ext))return `Định dạng tệp ${ext||'(không có phần mở rộng)'} không được hỗ trợ. Các định dạng được phép: ${policy.allowedExtensions.join(', ')}.`;
  if(file.size>policy.maxSizeBytes)return `Dung lượng tệp vượt quá giới hạn ${(policy.maxSizeBytes/1024/1024).toFixed(0)}MB cho phép.`;
  return null;
}
export function documentFileSelection<T extends UploadFile>(file:T|null|undefined,policy?:DocumentCapabilityPolicy):{file:T|null;error:string|null}{
  if(!file)return {file:null,error:null};
  const error=documentFileError(file,policy);
  return {file:error?null:file,error};
}
