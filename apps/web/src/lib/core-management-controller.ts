import type {CoreAcademicYear,CoreAdminUser,CoreApiPort,CoreClass,CoreCourse,CoreHomeroom,CoreMember,CoreOptions,CorePreview,CoreRoster,CoreSemester,CoreTeacher} from './api/core-contract';
import type {IssuedCode,RouteParams} from './domain';
import {ApiError,errorMessage} from './api/errors';
import {resourceUuid} from './api/operations';
import {allCorePages} from './data/live-classroom-social';

export const coreManagementRoutes=['a.accounts','a.account','a.catalog','a.homerooms','a.homeroom','a.classes','a.newClass','a.classSettings','a.enrollment','a.lifecycle'] as const;
export type CoreManagementRoute=typeof coreManagementRoutes[number];
export type ManagementOperation='createCourse'|'createHomeroom'|'setRoster'|'transferHomeroom'|'createClass'|'setTeachers'|'syncEnrollment'|'setEnrollmentMode'|'addMember'|'endMember'|'transferMember'|'archiveClass'|'restoreClass'|'setUserStatus'|'setUserRoles';
export type ManagementCommand=<K extends ManagementOperation>(operation:K,options:CoreOptions<K>)=>void;
export type CoreManagementState={busy:boolean;loaded:boolean;needsReload:boolean;unknown:boolean;reconciled:boolean;issue:{message:string;correlationId?:string}|null;notice:string|null;acknowledgement:{operation:ManagementOperation;resourceId:string|null}|null;users:CoreAdminUser[];courses:CoreCourse[];years:CoreAcademicYear[];semesters:CoreSemester[];homerooms:CoreHomeroom[];classes:CoreClass[];account:CoreAdminUser|null;klass:CoreClass|null;roster:CoreRoster|null;teachers:CoreTeacher[];members:CoreMember[];preview:CorePreview|null;issued:IssuedCode|null};
const initial=():CoreManagementState=>({busy:false,loaded:false,needsReload:false,unknown:false,reconciled:false,issue:null,notice:null,acknowledgement:null,users:[],courses:[],years:[],semesters:[],homerooms:[],classes:[],account:null,klass:null,roster:null,teachers:[],members:[],preview:null,issued:null});
function invalid(message:string):never{throw new ApiError('VALIDATION_ERROR',message,422);}
const same=(a:string,b:string)=>a.toLowerCase()===b.toLowerCase();

export function createCoreManagementController(api:CoreApiPort,context:{routeId:CoreManagementRoute;params:RouteParams;schoolId:string;isCurrentActor:()=>boolean;issueCode?:(id:string,verified:boolean)=>Promise<IssuedCode>}){
  let state=initial(),active=true;
  const abort=new AbortController(),listeners=new Set<()=>void>();
  const current=()=>active&&context.isCurrentActor();
  const check=()=>{if(!current())throw new ApiError('SESSION_CHANGED','Phiên đăng nhập đã thay đổi.',401);};
  const publish=(patch:Partial<CoreManagementState>)=>{if(current()){state={...state,...patch};listeners.forEach(listener=>listener());}};
  const scope=<T extends {school_id:string|null}>(rows:T[])=>{if(rows.some(row=>!row.school_id||!same(row.school_id,context.schoolId)))throw new ApiError('CONTRACT_MISMATCH','Dữ liệu không thuộc nhà trường hiện hành.');return rows;};
  async function read(){
    const signal=AbortSignal.any([abort.signal,AbortSignal.timeout(15000)]);
    const page=<T extends {id:string}>(load:(cursor?:string)=>Promise<{items:T[];next_cursor:string|null}>)=>allCorePages(cursor=>{check();return load(cursor);},signal);
    const base={limit:100,signal},isAccount=context.routeId==='a.accounts'||context.routeId==='a.account';
    if(isAccount){
      const [users,account]=await Promise.all([page(cursor=>api.request('adminUsers',{...base,cursor})),context.routeId==='a.account'?api.request('adminUser',{userId:context.params.userId,signal}):Promise.resolve(null)]);
      check();scope(users);if(account)scope([account]);publish({users,account,loaded:true,needsReload:false,reconciled:state.unknown,preview:null});return;
    }
    const [users,courses,years,homerooms,classes]=await Promise.all([
      page(cursor=>api.request('adminUsers',{...base,cursor})),page(cursor=>api.request('courses',{...base,cursor})),page(cursor=>api.request('academicYears',{...base,cursor})),page(cursor=>api.request('homerooms',{...base,cursor})),page(cursor=>api.request('classes',{...base,cursor})),
    ]);
    check();scope(users);scope(courses);scope(years);scope(homerooms);scope(classes);
    const semesters:CoreSemester[]=[];
    for(const year of years){const rows=await page(cursor=>api.request('semesters',{...base,cursor,yearId:year.id}));if(rows.some(row=>!same(row.academic_year_id,year.id)))throw new ApiError('CONTRACT_MISMATCH','Học kỳ không thuộc năm học.');semesters.push(...rows);}
    let klass:CoreClass|null=null,roster:CoreRoster|null=null,teachers:CoreTeacher[]=[],members:CoreMember[]=[];
    if(context.params.classId){
      [klass,teachers,members]=await Promise.all([api.request('classDetail',{classId:context.params.classId,signal}),api.request('teachingAssignments',{classId:context.params.classId,signal}),api.request('classMembers',{classId:context.params.classId,signal})]);scope([klass]);
    }
    if(context.params.homeroomId){
      if(!homerooms.some(row=>same(row.id,context.params.homeroomId)))throw new ApiError('NOT_FOUND','Không tìm thấy lớp hành chính.',404);
      roster=await api.request('roster',{homeroomId:context.params.homeroomId,signal});
    }
    check();publish({users,courses,years,semesters,homerooms,classes,klass,roster,teachers,members,loaded:true,needsReload:false,reconciled:state.unknown,preview:null});
  }
  function failed(error:unknown,mutation:boolean){
    publish({issue:{message:errorMessage(error),...(error instanceof ApiError&&error.correlationId?{correlationId:error.correlationId}:{})},
      ...(error instanceof ApiError&&[401,403,404].includes(error.status)?{...initial(),unknown:state.unknown,reconciled:false,acknowledgement:state.acknowledgement,issue:{message:errorMessage(error),correlationId:error.correlationId}}:{}),
      needsReload:!(mutation&&error instanceof ApiError&&error.status===422&&error.outcome==='rejected'),preview:null,
      ...(mutation&&error instanceof ApiError&&error.outcome==='unknown'?{unknown:true,reconciled:false}:{}),
    });
  }
  async function run(work:()=>Promise<void>,mutation=false){
    if(!current()||state.busy||mutation&&(!state.loaded||state.unknown||state.needsReload||Boolean(state.issued)))return;
    publish({busy:true,issue:null,notice:null,...(mutation?{acknowledgement:null}:{})});
    try{await work();}catch(error){failed(error,mutation);}finally{publish({busy:false});}
  }
  return {
    getState:()=>state,
    subscribe(listener:()=>void){listeners.add(listener);return()=>{listeners.delete(listener);};},
    dispose(){active=false;abort.abort();listeners.clear();state=initial();},
    load(){return run(read);},
    acknowledgeUnknown(){if(current()&&!state.busy&&state.unknown&&state.reconciled)publish({unknown:false,reconciled:false,notice:'Đã đối chiếu dữ liệu. Chưa có xác nhận thành công cho yêu cầu trước.'});},
    clearCode(){if(current()&&!state.busy)publish({issued:null});},
    issueCode(verified:boolean){return run(async()=>{
      const user=state.account,issuer=context.issueCode;if(!user||user.roles.length!==1||user.roles[0]!=='STUDENT'||!user.username||user.status==='LOCKED'||!issuer||!verified)invalid('Chọn học sinh đủ điều kiện và xác nhận đã kiểm tra danh tính.');
      const issued=await issuer(user.id,true);check();if(!same(issued.student.id,user.id)||!issued.student.school_id||!same(issued.student.school_id,context.schoolId))throw new ApiError('CONTRACT_MISMATCH','Mã cấp không khớp học sinh.',0,'unknown');publish({issued,notice:'Mã chỉ hiển thị ở lần cấp này. Bàn giao an toàn trước khi đóng.'});
    },true);},
    previewEnrollment(){return run(async()=>{
      if(state.unknown||state.needsReload||!state.klass||state.klass.status!=='ACTIVE')return;
      if(!state.klass.homeroom_class_id){publish({preview:null,issue:{message:'Lớp chưa liên kết lớp hành chính nên chưa thể xem trước ghi danh AUTO.'}});return;}
      publish({preview:null});const preview=await api.request('previewEnrollment',{classId:state.klass.id,signal:abort.signal});check();
      if(!same(preview.class_id,state.klass.id)||preview.class_version!==state.klass.version)throw new ApiError('CONFLICT','Lớp đã thay đổi. Tải lại trước khi xem tác động.',409);
      publish({preview});
    });},
    command<K extends ManagementOperation>(operation:K,options:CoreOptions<K>){return run(async()=>{
      if(options.classId&&(!state.klass||!same(options.classId,state.klass.id)))invalid('Lớp thao tác không khớp màn hình.');
      if(options.homeroomId&&(!state.roster||!same(options.homeroomId,state.roster.homeroom_class_id)))invalid('Lớp hành chính không khớp màn hình.');
      if(options.userId&&(!state.account||!same(options.userId,state.account.id)))invalid('Tài khoản không khớp màn hình.');
      for(const value of [options.classId,options.homeroomId,options.userId,options.studentId])if(value&&!resourceUuid.test(value))invalid('Định danh không hợp lệ.');
      if(operation==='setEnrollmentMode'&&(options.body as CoreOptions<'setEnrollmentMode'>['body']).mode==='AUTO'){
        const body=options.body as CoreOptions<'setEnrollmentMode'>['body'],preview=state.preview;
        if(!preview||body.expected_class_version!==preview.class_version||body.expected_roster_version!==preview.roster_version)invalid('Xem và xác nhận đúng tác động mới nhất trước khi chuyển AUTO.');
      }
      if(operation==='syncEnrollment'&&!state.preview)invalid('Xem tác động trước khi đồng bộ ghi danh.');
      const receipt=await api.request(operation,{...options,signal:abort.signal});check();
      const resourceId=receipt&&typeof receipt==='object'&&'id'in receipt&&typeof receipt.id==='string'?receipt.id:null;
      publish({acknowledgement:{operation,resourceId},notice:'Máy chủ đã xác nhận thao tác. Đang tải dữ liệu hiện hành.',needsReload:true,preview:null});
      try{await read();publish({notice:'Đã cập nhật và tải lại dữ liệu hiện hành.'});}catch(error){failed(error,false);publish({notice:'Máy chủ đã xác nhận thao tác; chưa tải lại được dữ liệu. Hãy tải lại trước khi thao tác tiếp.',needsReload:true});}
    },true);},
  };
}
export type CoreManagementController=ReturnType<typeof createCoreManagementController>;
