/** 食物分类 → Ant Design Tag 预设色。 */
export const CATEGORY_COLOR: Record<string, string> = {
  主食: 'geekblue',
  蛋白质: 'gold',
  蔬菜: 'green',
  水果: 'magenta',
  饮品: 'cyan',
  甜点零食: 'purple',
  汤: 'volcano',
  其他: 'default',
};

export function categoryColor(cat: string): string {
  return CATEGORY_COLOR[cat] ?? 'default';
}
