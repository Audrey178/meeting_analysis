interface ErrorBannerProps {
  message: string;
  onRetry: () => void;
  onEditInput: () => void;
}

export function ErrorBanner({ message, onRetry, onEditInput }: ErrorBannerProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-14">
      <div className="max-w-[60ch] border-l-2 border-accent bg-accent-100 p-5">
        <h2 className="mb-2 text-[22px] text-accent-800">Phân tích thất bại</h2>
        <p className="mb-4 text-[13.5px] break-words text-accent-800">{message}</p>
        <div className="flex gap-2.5">
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            Thử lại
          </button>
          <button type="button" className="btn btn-secondary" onClick={onEditInput}>
            Sửa transcript
          </button>
        </div>
      </div>
    </div>
  );
}
