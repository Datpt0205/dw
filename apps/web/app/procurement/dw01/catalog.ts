export const PROCUREMENT_TYPES = [
  {
    value: "goods",
    label: "Hàng hóa",
    shortLabel: "Hàng hóa",
    description: "Thiết bị, vật tư, phần mềm và hàng hóa hữu hình.",
  },
  {
    value: "construction",
    label: "Xây lắp",
    shortLabel: "Xây lắp",
    description: "Thi công, cải tạo và lắp đặt công trình.",
  },
  {
    value: "consulting",
    label: "Dịch vụ tư vấn",
    shortLabel: "Tư vấn",
    description: "Khảo sát, thiết kế, giám sát và tư vấn chuyên môn.",
  },
  {
    value: "non_consulting",
    label: "Dịch vụ phi tư vấn",
    shortLabel: "Phi tư vấn",
    description: "Vận hành, bảo trì, logistics và dịch vụ thực hiện.",
  },
  {
    value: "mixed",
    label: "Gói thầu hỗn hợp",
    shortLabel: "Hỗn hợp",
    description: "Kết hợp từ hai loại công việc trở lên.",
  },
  {
    value: "investor_selection",
    label: "Lựa chọn nhà đầu tư",
    shortLabel: "Nhà đầu tư",
    description: "Dự án có sử dụng đất hoặc cần lựa chọn nhà đầu tư.",
  },
  {
    value: "other",
    label: "Khác / chưa phân loại",
    shortLabel: "Khác",
    description: "Trường hợp chưa thuộc nhóm chuẩn.",
  },
] as const;

export const BUSINESS_DOMAINS = [
  { value: "general", label: "Mua sắm chung" },
  { value: "information_technology", label: "CNTT & chuyển đổi số" },
  { value: "real_estate", label: "Bất động sản & đất đai" },
  { value: "healthcare", label: "Y tế & dược" },
  { value: "infrastructure", label: "Hạ tầng & xây dựng" },
  { value: "operations", label: "Vận hành doanh nghiệp" },
  { value: "energy", label: "Năng lượng & tiện ích" },
  { value: "education", label: "Giáo dục & đào tạo" },
  { value: "other", label: "Lĩnh vực khác" },
] as const;

export function procurementTypeLabel(value: string): string {
  return (
    PROCUREMENT_TYPES.find((item) => item.value === value)?.shortLabel ?? value
  );
}

export function businessDomainLabel(value: string): string {
  return BUSINESS_DOMAINS.find((item) => item.value === value)?.label ?? value;
}
