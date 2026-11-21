import { Page } from '@playwright/test';

/**
 * The page content. Tooltips repeat a name in a hidden node outside it, so a lookup by
 * text over the whole page finds two matches.
 */
export const content = (page: Page) => page.getByRole('main');

/** The table row of the item named `name` (a video shows its name without extension). */
export const row = (page: Page, name: string) =>
  content(page).locator('tbody tr')
    // The inner locator of `has` is resolved inside each row, so it must start from
    // `page`: one starting from `content(page)` would look for a <main> in the row.
    .filter({ has: page.getByText(name, { exact: true }) });

/** Opens the file browser and walks down to the directory at `path`. */
export async function openDirectory(page: Page, ...path: string[]) {
  await page.goto('/file-browser');
  // The tab reopens the directory it was last in, so start over from the root crumb.
  await page.getByTitle('Root', { exact: true }).click();
  for (const directory of path) {
    await row(page, directory).click();
  }
}
