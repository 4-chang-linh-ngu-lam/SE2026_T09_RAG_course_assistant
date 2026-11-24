'use client';

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { Brand } from '@/components/ui';
import './landing-page.css';

// SVG Icon Helper following Phosphor / Solar style
function LandingIcon({ name, className = '' }: { name: string; className?: string }) {
  const iconMap: Record<string, React.ReactNode> = {
    newspaper: (
      <>
        <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z" />
        <path d="M8 8h8M8 12h8M8 16h4" />
      </>
    ),
    calendar: (
      <>
        <rect x="3" y="4" width="18" height="17" rx="3" />
        <path d="M8 2v4M16 2v4M3 9h18" />
        <circle cx="8" cy="14" r="1" fill="currentColor" />
        <circle cx="12" cy="14" r="1" fill="currentColor" />
        <circle cx="16" cy="14" r="1" fill="currentColor" />
      </>
    ),
    sparkles: (
      <>
        <path d="m12 3 2.2 5.5L20 11l-5.8 2.5L12 19l-2.2-5.5L4 11l5.8-2.5Z" />
        <path d="m19 2 1 2.5L22.5 5.5 20 6.5 19 9l-1-2.5L15.5 5.5 18 4.5Z" />
      </>
    ),
    shieldCheck: (
      <>
        <path d="M12 2 4 5.5v6.2c0 5 3.4 9.6 8 10.8 4.6-1.2 8-5.8 8-10.8V5.5L12 2Z" />
        <path d="m9 12 2 2 4-4" />
      </>
    ),
    bookOpen: (
      <>
        <path d="M2 5.5A2.5 2.5 0 0 1 4.5 3h6A2.5 2.5 0 0 1 13 5.5V19a2 2 0 0 0-2-2H4.5A2.5 2.5 0 0 0 2 19.5v-14Z" />
        <path d="M22 5.5A2.5 2.5 0 0 0 19.5 3h-6A2.5 2.5 0 0 0 11 5.5V19a2 2 0 0 1 2-2h6.5a2.5 2.5 0 0 1 2.5 2.5v-14Z" />
      </>
    ),
    arrowRight: (
      <>
        <path d="M5 12h14M13 6l6 6-6 6" />
      </>
    ),
    key: (
      <>
        <circle cx="8" cy="15" r="5" />
        <path d="m11.5 11.5 8.5-8.5M16 3l4 4M14 5l2 2" />
      </>
    ),
    chatCentered: (
      <>
        <path d="M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 4V5Z" />
      </>
    ),
    checkCircle: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="m8.5 12 2.5 2.5 4.5-5" />
      </>
    ),
    warningCircle: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v4M12 16h.01" />
      </>
    ),
    chevronDown: (
      <>
        <path d="m6 9 6 6 6-6" />
      </>
    ),
    menu: (
      <>
        <path d="M4 6h16M4 12h16M4 18h16" />
      </>
    ),
    close: (
      <>
        <path d="m6 6 12 12M6 18 18 6" />
      </>
    ),
    user: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M5 20a7 7 0 0 1 14 0" />
      </>
    ),
    clock: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
    quote: (
      <>
        <path d="M10 11H6a3 3 0 0 1 3-3V6a5 5 0 0 0-5 5v7h6v-7ZM20 11h-4a3 3 0 0 1 3-3V6a5 5 0 0 0-5 5v7h6v-7Z" />
      </>
    ),
  };

  return (
    <svg
      className={`landing-svg ${className}`}
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {iconMap[name] ?? <circle cx="12" cy="12" r="9" />}
    </svg>
  );
}

// B11 Mandatory Tagline Reveal Component
const TAGLINE_WORDS = [
  'Một',
  'không',
  'gian',
  'học',
  'tập',
  'chuẩn',
  'mực',
  'không',
  'chỉ',
  'lưu',
  'trữ',
  'bài',
  'vở,',
  'mà',
  'phải',
  'giúp',
  'từng',
  'học',
  'sinh',
  'tự',
  'tin',
  'tiếp',
  'thu',
  'kiến',
  'thức',
  'mỗi',
  'ngày.',
];

function TaglineReveal() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeCount, setActiveCount] = useState<number>(0);
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setPrefersReducedMotion(mediaQuery.matches);

    const handleChange = (e: MediaQueryListEvent) => setPrefersReducedMotion(e.matches);
    mediaQuery.addEventListener('change', handleChange);

    if (mediaQuery.matches) {
      setActiveCount(TAGLINE_WORDS.length);
      return () => mediaQuery.removeEventListener('change', handleChange);
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const ratio = Math.max(0, Math.min(1, (entry.intersectionRatio - 0.2) / 0.6));
            const wordsToActivate = Math.floor(ratio * TAGLINE_WORDS.length);
            setActiveCount((prev) => Math.max(prev, wordsToActivate));
          }
        });
      },
      {
        threshold: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        rootMargin: '0px 0px -10% 0px',
      }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => {
      mediaQuery.removeEventListener('change', handleChange);
      observer.disconnect();
    };
  }, []);

  return (
    <section ref={containerRef} className="landing-tagline-section" aria-label="Tuyên ngôn giá trị Lumi">
      <div className="landing-container">
        <div className="landing-tagline-card">
          <span className="landing-eyebrow">TRIẾT LÝ HỌC TẬP TẠI LUMI</span>
          <h2 className="landing-tagline-text">
            {TAGLINE_WORDS.map((word, idx) => {
              const isActive = prefersReducedMotion || idx < activeCount;
              return (
                <span
                  key={`${word}-${idx}`}
                  className={`landing-reveal-word ${isActive ? 'is-active' : ''}`}
                >
                  {word}{' '}
                </span>
              );
            })}
          </h2>
          <p className="landing-tagline-sub">
            Thiết kế riêng cho các trường THCS và THPT với quy trình bảo mật chuẩn mực giáo dục.
          </p>
        </div>
      </div>
    </section>
  );
}

// Hero Interactive Preview Mockup Component
function HeroPreviewMockup() {
  const [activeTab, setActiveTab] = useState<'feed' | 'calendar' | 'tutor'>('feed');

  return (
    <div className="landing-mockup" aria-label="Minh họa giao diện làm việc Lumi">
      <div className="landing-mockup-bar">
        <div className="landing-mockup-dots" aria-hidden="true">
          <span className="dot red" />
          <span className="dot yellow" />
          <span className="dot green" />
        </div>
        <div className="landing-mockup-url">
          <span>lumi.edu.vn/lop-hoc/toan-10a1</span>
        </div>
        <div className="landing-mockup-status">
          <span className="live-badge">Trực tuyến</span>
        </div>
      </div>

      <div className="landing-mockup-body">
        <aside className="landing-mockup-sidebar" aria-label="Thanh bên minh họa">
          <div className="mockup-user-info">
            <div className="mockup-avatar">TK</div>
            <div>
              <strong>Tuấn Kiệt</strong>
              <small>Lớp 10A1</small>
            </div>
          </div>
          <nav className="mockup-nav" aria-label="Menu chức năng minh họa">
            <button
              type="button"
              className={`mockup-nav-btn ${activeTab === 'feed' ? 'active' : ''}`}
              onClick={() => setActiveTab('feed')}
            >
              <LandingIcon name="newspaper" />
              <span>Bảng tin môn học</span>
            </button>
            <button
              type="button"
              className={`mockup-nav-btn ${activeTab === 'calendar' ? 'active' : ''}`}
              onClick={() => setActiveTab('calendar')}
            >
              <LandingIcon name="calendar" />
              <span>Lịch và Hạn nộp</span>
            </button>
            <button
              type="button"
              className={`mockup-nav-btn ${activeTab === 'tutor' ? 'active' : ''}`}
              onClick={() => setActiveTab('tutor')}
            >
              <LandingIcon name="sparkles" />
              <span>Trợ giảng AI</span>
            </button>
          </nav>
        </aside>

        <main className="landing-mockup-main">
          {activeTab === 'feed' && (
            <div className="mockup-panel">
              <div className="mockup-panel-header">
                <div>
                  <span className="mockup-tag">MÔN TOÁN HỌC 10</span>
                  <h3>Bảng tin thảo luận lớp 10A1</h3>
                </div>
                <span className="mockup-pill-info">28 thành viên</span>
              </div>

              <div className="mockup-post-card">
                <div className="mockup-post-head">
                  <div className="mockup-teacher-avatar">MT</div>
                  <div>
                    <strong>Cô Mai Trang</strong>
                    <small>Giáo viên bộ môn · 08:30 sáng nay</small>
                  </div>
                </div>
                <p className="mockup-post-content">
                  Các em hoàn thành phiếu bài tập tuần 14 về Vectơ trong mặt phẳng tọa độ trước 21h00 Thứ Năm. Tài liệu hướng dẫn phương pháp đã đính kèm bên dưới.
                </p>
                <div className="mockup-attachment">
                  <LandingIcon name="bookOpen" />
                  <div>
                    <strong>Phieu_Bai_Tap_Tuan_14_Vecto.pdf</strong>
                    <small>Tài liệu học tập chính khóa · 1.4 MB</small>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'calendar' && (
            <div className="mockup-panel">
              <div className="mockup-panel-header">
                <div>
                  <span className="mockup-tag">THỜI KHÓA BIỂU & NHẮC VIỆC</span>
                  <h3>Lịch học tập Tuần 14</h3>
                </div>
                <span className="mockup-pill-info">Học kỳ 1</span>
              </div>

              <div className="mockup-events-list">
                <div className="mockup-event-item">
                  <div className="mockup-event-time">
                    <strong>07:30</strong>
                    <small>Thứ Ba</small>
                  </div>
                  <div className="mockup-event-desc">
                    <strong>Tiết 1 và 2: Toán học Đại số</strong>
                    <p>Phòng 204 · Thầy Nam phụ trách</p>
                  </div>
                  <span className="mockup-status-tag ongoing">Sắp tới</span>
                </div>

                <div className="mockup-event-item highlight">
                  <div className="mockup-event-time">
                    <strong>21:00</strong>
                    <small>Thứ Năm</small>
                  </div>
                  <div className="mockup-event-desc">
                    <strong>Hạn nộp: Bài tập chuyên đề Vectơ</strong>
                    <p>Nộp file bài làm trực tiếp trên hệ thống</p>
                  </div>
                  <span className="mockup-status-tag due">Hạn nộp</span>
                </div>

                <div className="mockup-event-item">
                  <div className="mockup-event-time">
                    <strong>09:15</strong>
                    <small>Thứ Sáu</small>
                  </div>
                  <div className="mockup-event-desc">
                    <strong>Kiểm tra 15 phút: Vật lý 10</strong>
                    <p>Chương 2 Động lực học chất điểm</p>
                  </div>
                  <span className="mockup-status-tag test">Kiểm tra</span>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'tutor' && (
            <div className="mockup-panel">
              <div className="mockup-panel-header">
                <div>
                  <span className="mockup-tag">TRỢ GIẢNG AI CÓ TRÍCH DẪN</span>
                  <h3>Giải đáp kiến thức theo bài học</h3>
                </div>
                <span className="mockup-pill-ai">Mô hình RAG Lumi</span>
              </div>

              <div className="mockup-chat-thread">
                <div className="mockup-bubble user">
                  <p>Trợ giảng giải thích giúp em điều kiện hai vectơ cùng phương và cách kiểm tra nhanh với tọa độ?</p>
                </div>
                <div className="mockup-bubble ai">
                  <div className="ai-author-row">
                    <LandingIcon name="sparkles" />
                    <strong>Lumi AI Tutor</strong>
                  </div>
                  <p>
                    Hai vectơ cùng phương khi giá của chúng song song hoặc trùng nhau. Với hai vectơ u(x1; y1) và v(x2; y2) khác vectơ không, u cùng phương với v khi và chỉ khi tồn tại số thực k sao cho u = kv, tương đương tỉ số tọa độ x1/x2 = y1/y2.
                  </p>
                  <div className="ai-citation-box">
                    <LandingIcon name="shieldCheck" />
                    <span>Căn cứ nguồn: Sách giáo khoa Toán 10 · Bài 2 Hệ trục tọa độ · Trang 65</span>
                  </div>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

// FAQ Accordion Item Component
function FaqItem({
  question,
  answer,
  isOpen,
  onToggle,
}: {
  question: string;
  answer: string;
  isOpen: boolean;
  onToggle: () => void;
}) {
  return (
    <div className={`landing-faq-item ${isOpen ? 'is-open' : ''}`}>
      <button
        type="button"
        className="landing-faq-question"
        onClick={onToggle}
        aria-expanded={isOpen}
      >
        <span>{question}</span>
        <LandingIcon name="chevronDown" className="faq-chevron" />
      </button>
      {isOpen && (
        <div className="landing-faq-answer">
          <p>{answer}</p>
        </div>
      )}
    </div>
  );
}

export function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0);

  const toggleFaq = (index: number) => {
    setOpenFaqIndex(openFaqIndex === index ? null : index);
  };

  const faqList = [
    {
      q: 'Làm thế nào để học sinh nhận được tài khoản Lumi?',
      a: 'Tài khoản học sinh được khởi tạo đồng bộ bởi ban giám hiệu và giáo viên nhà trường. Học sinh nhận mã kích hoạt một lần (One-Time Token) để tạo mật khẩu đăng nhập, đảm bảo danh tính chính xác và an toàn tuyệt đối.',
    },
    {
      q: 'Học sinh có thể tự đăng ký tài khoản tự do trên trang web không?',
      a: 'Không. Để duy trì môi trường lớp học chuẩn mực, Lumi không hỗ trợ mở tài khoản tự do hoặc mã tham gia lớp công khai. Chỉ những học sinh thuộc danh sách phân công lớp chính khóa của trường mới được cấp quyền truy cập.',
    },
    {
      q: 'Trợ giảng AI của Lumi trả lời có đáng tin cậy không?',
      a: 'Trợ giảng Lumi vận hành theo kiến trúc RAG (Retrieval-Augmented Generation), chỉ tìm kiếm và đối chiếu trên kho bài giảng, đề cương và sách giáo khoa đã được thầy cô phê duyệt. Mọi câu trả lời đều ghi chú rõ nguồn tài liệu, không tự bịa đặt kiến thức.',
    },
    {
      q: 'Lumi có sử dụng mượt mà trên điện thoại thông minh không?',
      a: 'Giao diện Lumi được thiết kế thích ứng hoàn toàn trên mọi độ phân giải từ điện thoại di động (tối ưu từ 390px), máy tính bảng đến máy tính để bàn, giúp học sinh tra cứu lịch và bảng tin thuận tiện mọi lúc.',
    },
    {
      q: 'Nếu học sinh quên mật khẩu thì giải quyết bằng cách nào?',
      a: 'Học sinh có thể liên hệ với giáo viên chủ nhiệm hoặc cán bộ quản trị trường để được cấp lại mã thiết lập mật khẩu mới một cách an toàn và nhanh chóng.',
    },
    {
      q: 'Dữ liệu học tập và thông tin cá nhân của học sinh được bảo vệ thế nào?',
      a: 'Hệ thống tuân thủ nghiêm ngặt quy chế phân quyền theo lớp học. Dữ liệu ghi chú cá nhân, lịch sử hỏi đáp và điểm số chỉ hiển thị cho đúng học sinh và giáo viên phụ trách, tuyệt đối không chia sẻ cho bên thứ ba.',
    },
  ];

  return (
    <div className="landing">
      {/* Floating Header */}
      <header className="landing-header">
        <div className="landing-header-pill">
          <Brand href="/gioi-thieu" />

          <nav className="landing-nav-desktop" aria-label="Điều hướng trang chủ">
            <a href="#tinh-nang">Tính năng</a>
            <a href="#cach-hoat-dong">Cách hoạt động</a>
            <a href="#tro-giang-ai">Trợ giảng AI</a>
            <a href="#hoi-dap">Hỏi đáp</a>
          </nav>

          <div className="landing-header-actions">
            <Link href="/activate" className="landing-btn-secondary">
              Kích hoạt tài khoản
            </Link>
            <Link href="/login" className="landing-btn-primary">
              Đăng nhập
            </Link>
            <button
              type="button"
              className="landing-mobile-toggle"
              aria-label={mobileMenuOpen ? 'Đóng menu' : 'Mở menu'}
              aria-expanded={mobileMenuOpen}
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            >
              <LandingIcon name={mobileMenuOpen ? 'close' : 'menu'} />
            </button>
          </div>
        </div>

        {/* Mobile Full Screen Menu Panel */}
        {mobileMenuOpen && (
          <div className="landing-mobile-drawer" role="dialog" aria-modal="true">
            <nav className="landing-mobile-nav" aria-label="Menu trên điện thoại">
              <a href="#tinh-nang" onClick={() => setMobileMenuOpen(false)}>
                Tính năng
              </a>
              <a href="#cach-hoat-dong" onClick={() => setMobileMenuOpen(false)}>
                Cách hoạt động
              </a>
              <a href="#tro-giang-ai" onClick={() => setMobileMenuOpen(false)}>
                Trợ giảng AI
              </a>
              <a href="#hoi-dap" onClick={() => setMobileMenuOpen(false)}>
                Hỏi đáp
              </a>
              <div className="landing-mobile-cta">
                <Link href="/activate" className="button" onClick={() => setMobileMenuOpen(false)}>
                  Kích hoạt tài khoản
                </Link>
                <Link
                  href="/login"
                  className="button primary"
                  onClick={() => setMobileMenuOpen(false)}
                >
                  Đăng nhập vào Lumi
                </Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      <main id="main-content">
        {/* Hero Section */}
        <section className="landing-hero-section" aria-labelledby="hero-title">
          <div className="landing-container">
            <div className="landing-hero-head">
              <div className="landing-badge">
                <LandingIcon name="sparkles" className="badge-icon" />
                <span>KHÔNG GIAN LỚP HỌC PHỔ THÔNG CHÍNH KHÓA</span>
              </div>

              <h1 id="hero-title" className="landing-hero-title">
                Học tập có định hướng
                <br />
                cho học sinh và giáo viên phổ thông
              </h1>

              <p className="landing-hero-desc">
                Lumi kết nối bảng tin lớp học, thời khóa biểu và trợ giảng thông minh có dẫn nguồn
                trong cùng một không gian số tập trung, giúp việc dạy và học luôn liền mạch.
              </p>

              <div className="landing-hero-actions">
                <Link href="/login" className="landing-btn-hero-primary">
                  Đăng nhập vào Lumi
                  <LandingIcon name="arrowRight" />
                </Link>
                <Link href="/activate" className="landing-btn-hero-secondary">
                  <LandingIcon name="key" />
                  Kích hoạt bằng mã trường cấp
                </Link>
              </div>

              <div className="landing-hero-proof">
                <div className="proof-check-item">
                  <LandingIcon name="shieldCheck" />
                  <span>Chuẩn hóa khối 6 đến khối 12</span>
                </div>
                <div className="proof-check-item">
                  <LandingIcon name="checkCircle" />
                  <span>Khởi tạo bảo mật bởi nhà trường</span>
                </div>
                <div className="proof-check-item">
                  <LandingIcon name="checkCircle" />
                  <span>100% học liệu có kiểm duyệt</span>
                </div>
              </div>
            </div>

            {/* Interactive Hero Product Preview */}
            <HeroPreviewMockup />
          </div>
        </section>

        {/* Metrics Bar */}
        <section className="landing-metrics-section" aria-label="Các chỉ số tin cậy">
          <div className="landing-container">
            <div className="landing-metrics-grid">
              <div className="metric-box">
                <strong className="metric-num">Khối 6 – 12</strong>
                <span className="metric-title">Khung chương trình chuẩn</span>
                <p className="metric-desc">Tổ chức lớp học theo từng môn và khối học phổ thông</p>
              </div>
              <div className="metric-box">
                <strong className="metric-num">1 Nơi tập trung</strong>
                <span className="metric-title">Không còn trôi bài</span>
                <p className="metric-desc">Bảng tin, tài liệu và lịch học gói gọn trong một nền tảng</p>
              </div>
              <div className="metric-box">
                <strong className="metric-num">100% Có dẫn chứng</strong>
                <span className="metric-title">Trợ giảng AI tin cậy</span>
                <p className="metric-desc">Mọi giải đáp đều trích dẫn chính xác bài học và trang sách</p>
              </div>
              <div className="metric-box">
                <strong className="metric-num">Bảo mật cao</strong>
                <span className="metric-title">Quản lý định danh</span>
                <p className="metric-desc">Phân quyền chặt chẽ giữa giáo viên, học sinh và nhà trường</p>
              </div>
            </div>
          </div>
        </section>

        {/* B11 Mandatory Tagline Scroll Reveal */}
        <TaglineReveal />

        {/* Problem to Solution Section */}
        <section className="landing-contrast-section" aria-labelledby="contrast-heading">
          <div className="landing-container">
            <div className="landing-section-intro">
              <span className="landing-eyebrow">GIẢI PHÁP CHUYÊN BIỆT</span>
              <h2 id="contrast-heading">
                Từ những nhóm chat rời rạc
                <br />
                đến không gian học tập chuẩn mực
              </h2>
              <p>
                Khắc phục hoàn toàn những nhược điểm khi dùng mạng xã hội cho việc trao đổi học tập chính khóa.
              </p>
            </div>

            <div className="landing-contrast-grid">
              {/* Problem Card */}
              <div className="contrast-card before">
                <div className="contrast-card-head">
                  <span className="contrast-icon-bad">
                    <LandingIcon name="warningCircle" />
                  </span>
                  <div>
                    <h3>Khi chưa có Lumi</h3>
                    <small>Nhiều khó khăn trong trao đổi hàng ngày</small>
                  </div>
                </div>
                <ul className="contrast-list">
                  <li>
                    <span className="contrast-bullet bad">✕</span>
                    <p>Thông báo bài tập bị trôi giữa hàng trăm tin nhắn phụ huynh và học sinh.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet bad">✕</span>
                    <p>Tài liệu gửi rải rác qua nhiều đường link lưu trữ khác nhau, rất khó tìm lại.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet bad">✕</span>
                    <p>Học sinh dễ quên hạn nộp bài tập và lịch kiểm tra do không có lịch nhắc tập trung.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet bad">✕</span>
                    <p>Hỏi bài trên mạng gặp nhiều câu trả lời sai lệch, thiếu cơ sở kiến thức chuẩn.</p>
                  </li>
                </ul>
              </div>

              {/* Solution Card */}
              <div className="contrast-card after">
                <div className="contrast-card-head">
                  <span className="contrast-icon-good">
                    <LandingIcon name="checkCircle" />
                  </span>
                  <div>
                    <h3>Khi đồng hành cùng Lumi</h3>
                    <small>Khoa học, minh bạch và an tâm</small>
                  </div>
                </div>
                <ul className="contrast-list">
                  <li>
                    <span className="contrast-bullet good">✓</span>
                    <p>Bảng tin chuyên biệt cho từng môn, bài đăng quan trọng luôn được ghim đầu trang.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet good">✓</span>
                    <p>Kho học liệu số hóa theo tuần học, mở xem trực tiếp tài liệu không lo thất lạc.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet good">✓</span>
                    <p>Thời khóa biểu và hạn bài tự động hiển thị, nhắc nhở rõ ràng từng mốc thời gian.</p>
                  </li>
                  <li>
                    <span className="contrast-bullet good">✓</span>
                    <p>Trợ giảng AI hỗ trợ giải thích phương pháp giải, dẫn chứng chuẩn xác bài học của thầy cô.</p>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </section>

        {/* Bento Grid Features Section */}
        <section id="tinh-nang" className="landing-features-section" aria-labelledby="features-heading">
          <div className="landing-container">
            <div className="landing-section-intro">
              <span className="landing-eyebrow">TÍNH NĂNG NỔI BẬT</span>
              <h2 id="features-heading">Mọi công cụ cần thiết cho một buổi học hiệu quả</h2>
              <p>Được thiết kế tối giản, tập trung vào công tác giảng dạy và nâng cao năng lực tự học.</p>
            </div>

            <div className="landing-bento-grid">
              {/* Feature 1 */}
              <div className="bento-card bento-span-2">
                <div className="bento-icon-box">
                  <LandingIcon name="newspaper" />
                </div>
                <span className="bento-category">TỔ CHỨC LỚP HỌC</span>
                <h3>Bảng tin lớp học không xao nhãng</h3>
                <p>
                  Trao đổi bài học trọng tâm và văn minh. Giáo viên đăng tải thông báo chính thức,
                  học sinh thảo luận câu hỏi theo từng chủ đề bài viết mà không bị lẫn tạp âm tin nhắn rác.
                </p>
                <div className="bento-mini-preview">
                  <div className="mini-feed-item">
                    <div className="mini-avatar">GV</div>
                    <div>
                      <strong>Chuyên đề Ôn thi Học kỳ 1</strong>
                      <small>Thảo luận đã giải quyết 14 thắc mắc của học sinh</small>
                    </div>
                  </div>
                </div>
              </div>

              {/* Feature 2 */}
              <div className="bento-card">
                <div className="bento-icon-box">
                  <LandingIcon name="calendar" />
                </div>
                <span className="bento-category">QUẢN LÝ THỜI GIAN</span>
                <h3>Lịch học và Hạn nộp tự động</h3>
                <p>
                  Theo dõi thời khóa biểu hàng tuần, ngày nộp bài tập và lịch kiểm tra 15 phút, 1 tiết.
                  Không lo bỏ lỡ bất kỳ nhiệm vụ học tập nào.
                </p>
              </div>

              {/* Feature 3 */}
              <div className="bento-card" id="tro-giang-ai">
                <div className="bento-icon-box accent">
                  <LandingIcon name="sparkles" />
                </div>
                <span className="bento-category accent">CÔNG NGHỆ RAG TIÊN TIẾN</span>
                <h3>Trợ giảng AI có dẫn nguồn bài học</h3>
                <p>
                  Giải đáp thắc mắc của học sinh ngay lập tức với cơ chế đối chiếu tài liệu đã duyệt.
                  Từng câu trả lời đều chỉ rõ trang sách và đề cương bài học của giáo viên.
                </p>
              </div>

              {/* Feature 4 */}
              <div className="bento-card bento-span-2">
                <div className="bento-icon-box">
                  <LandingIcon name="shieldCheck" />
                </div>
                <span className="bento-category">BẢO MẬT HỌC ĐƯỜNG</span>
                <h3>Phân quyền chặt chẽ và Định danh an toàn</h3>
                <p>
                  Nhà trường kiểm soát 100% tài khoản lớp học. Không ai ngoài thành viên được phân công có thể xem tài liệu hoặc tham gia thảo luận của lớp.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* How It Works (3 Steps) */}
        <section id="cach-hoat-dong" className="landing-steps-section" aria-labelledby="steps-heading">
          <div className="landing-container">
            <div className="landing-section-intro">
              <span className="landing-eyebrow">QUY TRÌNH BA BƯỚC</span>
              <h2 id="steps-heading">Bắt đầu học tập dễ dàng cùng Lumi</h2>
              <p>Chỉ cần ba bước đơn giản để kết nối trọn vẹn vào lớp học chính khóa của bạn.</p>
            </div>

            <div className="landing-steps-grid">
              <div className="step-card">
                <div className="step-badge">Bước 1</div>
                <div className="step-icon">
                  <LandingIcon name="key" />
                </div>
                <h3>Nhận mã kích hoạt</h3>
                <p>
                  Nhà trường và giáo viên tạo danh sách lớp. Học sinh nhận mã kích hoạt một lần để khởi tạo mật khẩu cá nhân an toàn.
                </p>
              </div>

              <div className="step-card">
                <div className="step-badge">Bước 2</div>
                <div className="step-icon">
                  <LandingIcon name="bookOpen" />
                </div>
                <h3>Vào lớp và Xem lịch</h3>
                <p>
                  Hệ thống tự động đưa bạn vào đúng các lớp môn học đã được phân công. Nắm bắt thời khóa biểu và bảng tin lớp ngay lập tức.
                </p>
              </div>

              <div className="step-card">
                <div className="step-badge">Bước 3</div>
                <div className="step-icon">
                  <LandingIcon name="sparkles" />
                </div>
                <h3>Học tập và Tương tác</h3>
                <p>
                  Tải học liệu, nộp bài tập đúng hạn và đặt câu hỏi cho giáo viên cũng như trợ giảng AI bất cứ khi nào cần giải đáp.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Testimonials Section */}
        <section className="landing-testimonials-section" aria-labelledby="testimonials-heading">
          <div className="landing-container">
            <div className="landing-section-intro">
              <span className="landing-eyebrow">Ý KIẾN ĐÁNH GIÁ</span>
              <h2 id="testimonials-heading">Được tin chọn bởi thầy cô và học sinh</h2>
              <p>Trải nghiệm chân thực từ những người trực tiếp sử dụng Lumi trong năm học.</p>
            </div>

            <div className="landing-testimonials-grid">
              <div className="testimonial-card">
                <LandingIcon name="quote" className="quote-icon" />
                <p className="testimonial-quote">
                  Học sinh trong lớp không còn than phiền bị trôi thông báo bài tập như hồi dùng mạng xã hội. Mọi tài liệu và hạn nộp đều nằm ngay ngắn trong từng môn học.
                </p>
                <div className="testimonial-author">
                  <div className="author-avatar">NT</div>
                  <div>
                    <strong>Cô Nguyễn Thu Trang</strong>
                    <small>Giáo viên Toán học · Trường THPT Chuyên</small>
                  </div>
                </div>
              </div>

              <div className="testimonial-card">
                <LandingIcon name="quote" className="quote-icon" />
                <p className="testimonial-quote">
                  Tôi đánh giá rất cao việc trợ giảng AI chỉ trả lời dựa trên học liệu do tôi tải lên và phê duyệt, không tự đưa thông tin sai lệch ngoài chương trình giáo dục phổ thông.
                </p>
                <div className="testimonial-author">
                  <div className="author-avatar">TH</div>
                  <div>
                    <strong>Thầy Trần Hải Nam</strong>
                    <small>Giáo viên Chủ nhiệm · Trường THCS Chu Văn An</small>
                  </div>
                </div>
              </div>

              <div className="testimonial-card">
                <LandingIcon name="quote" className="quote-icon" />
                <p className="testimonial-quote">
                  Mỗi lần chuẩn bị kiểm tra học kỳ, em chỉ cần mở mục Lịch là biết rõ tuần này phải nộp bài những môn nào. Trợ giảng AI hướng dẫn phương pháp giải rất dễ hiểu.
                </p>
                <div className="testimonial-author">
                  <div className="author-avatar">LM</div>
                  <div>
                    <strong>Em Lê Minh Khoa</strong>
                    <small>Học sinh lớp 11A2</small>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ Section */}
        <section id="hoi-dap" className="landing-faq-section" aria-labelledby="faq-heading">
          <div className="landing-container">
            <div className="landing-section-intro">
              <span className="landing-eyebrow">GIẢI ĐÁP THẮC MẮC</span>
              <h2 id="faq-heading">Câu hỏi thường gặp</h2>
              <p>Mọi điều bạn cần biết về quyền lợi, cách sử dụng và tính bảo mật của Lumi.</p>
            </div>

            <div className="landing-faq-list">
              {faqList.map((item, idx) => (
                <FaqItem
                  key={item.q}
                  question={item.q}
                  answer={item.a}
                  isOpen={openFaqIndex === idx}
                  onToggle={() => toggleFaq(idx)}
                />
              ))}
            </div>
          </div>
        </section>

        {/* Final CTA Section */}
        <section className="landing-final-cta-section" aria-labelledby="final-cta-heading">
          <div className="landing-container">
            <div className="landing-final-card">
              <span className="landing-eyebrow-accent">MÔI TRƯỜNG HỌC TẬP THÂN THIỆN</span>
              <h2 id="final-cta-heading">
                Sẵn sàng bước vào không gian học tập Lumi?
              </h2>
              <p>
                Nếu bạn đã được nhà trường cung cấp mã kích hoạt hoặc tài khoản, hãy đăng nhập ngay để bắt đầu những giờ học hiệu quả.
              </p>
              <div className="landing-final-actions">
                <Link href="/login" className="landing-btn-hero-primary">
                  Đăng nhập vào Lumi
                  <LandingIcon name="arrowRight" />
                </Link>
                <Link href="/activate" className="landing-btn-hero-secondary">
                  <LandingIcon name="key" />
                  Kích hoạt bằng mã trường cấp
                </Link>
              </div>
              <small className="landing-final-note">
                Hệ thống dành riêng cho học sinh và giáo viên phổ thông khối 6 đến khối 12
              </small>
            </div>
          </div>
        </section>
      </main>

      {/* Semantic Footer */}
      <footer className="landing-footer">
        <div className="landing-container">
          <div className="landing-footer-top">
            <div className="landing-footer-brand">
              <Brand href="/gioi-thieu" />
              <p>
                Không gian lớp học trực tuyến dành cho các trường phổ thông. Kết nối lớp học, bảng tin, lịch học tập và trợ giảng AI có dẫn nguồn.
              </p>
            </div>

            <div className="landing-footer-links">
              <div>
                <strong>Nền tảng</strong>
                <ul>
                  <li><a href="#tinh-nang">Bảng tin lớp học</a></li>
                  <li><a href="#tinh-nang">Thời khóa biểu</a></li>
                  <li><a href="#tro-giang-ai">Trợ giảng RAG AI</a></li>
                  <li><a href="#cach-hoat-dong">Quy trình tham gia</a></li>
                </ul>
              </div>

              <div>
                <strong>Hỗ trợ</strong>
                <ul>
                  <li><a href="#hoi-dap">Câu hỏi thường gặp</a></li>
                  <li><Link href="/activate">Kích hoạt tài khoản</Link></li>
                  <li><Link href="/recover">Quên mật khẩu</Link></li>
                  <li><Link href="/login">Đăng nhập cổng trường</Link></li>
                </ul>
              </div>
            </div>
          </div>

          <div className="landing-footer-bottom">
            <span>© 2026 Lumi · Học sáng hơn mỗi ngày. Chuẩn hóa giáo dục phổ thông.</span>
            <div className="landing-footer-legal">
              <span className="legal-badge">Bảo mật thông tin học đường</span>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
