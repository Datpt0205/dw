import { Card, CardContent, CardHeader, CardTitle } from "@dw/ui";
import { ApiStatus } from "../../features/platform/api-status";

export default function HomePage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Digital Worker Platform</h1>
      <p className="max-w-2xl text-sm text-slate-600 dark:text-slate-400">
        Nền tảng Digital Worker đa tenant với hai bounded context: Procurement
        Tender và Meeting &amp; Work Operations. Các module nghiệp vụ sẽ xuất
        hiện tại đây theo từng phase triển khai.
      </p>
      <div className="grid max-w-3xl grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Procurement Tender Worker</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-600 dark:text-slate-400">
            Phân tích hồ sơ mời thầu, ma trận tuân thủ và đề xuất có bằng chứng.
            (Phase 4)
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Work Operations Worker</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-slate-600 dark:text-slate-400">
            Từ transcript cuộc họp đến action item được phê duyệt và giao việc.
            (Phase 3)
          </CardContent>
        </Card>
      </div>
      <ApiStatus />
    </div>
  );
}
