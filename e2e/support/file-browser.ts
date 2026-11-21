import { Locator, Page } from '@playwright/test';

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

/** Names of everything listed in the table, in display order. */
export const listedNames = (page: Page) =>
  content(page).locator('tbody tr td:nth-child(3)').allInnerTexts()
    .then(names => names.map(n => n.trim()));

/** The cell of `name`'s row under the column headed `header`, wherever that column is. */
export async function cell(page: Page, name: string, header: string): Promise<Locator> {
  const headers = (await content(page).locator('thead th').allInnerTexts()).map(h => h.trim());
  const index = headers.indexOf(header);
  if (index < 0) throw new Error(`no column "${header}" among ${JSON.stringify(headers)}`);
  return row(page, name).locator('td').nth(index);
}

/** The tags shown in `name`'s row, sorted; a row without tags shows none. */
export async function tagsOf(page: Page, name: string): Promise<string[]> {
  const tags = (await (await cell(page, name, 'Tags')).locator('span').allInnerTexts())
    .map(t => t.trim())
    .filter(t => t !== '-');
  return tags.sort();
}

/** Opens the file browser and walks down to the directory at `path`. */
export async function openDirectory(page: Page, ...path: string[]) {
  await page.goto('/file-browser');
  // The tab reopens the directory it was last in, so start over from the root crumb.
  await page.getByTitle('Root', { exact: true }).click();
  for (const directory of path) {
    await row(page, directory).click();
  }
}

/** Opens the menu of `name`'s row and picks `item`. */
export async function rowMenu(page: Page, name: string, item: string) {
  // The last button of a row opens its menu.
  await row(page, name).getByRole('button').last().click();
  await page.getByRole('menuitem', { name: item }).click();
}

/** Edits `name` through its row menu; only the given fields are touched. */
export async function editVideo(
  page: Page,
  name: string,
  changes: { title?: string; creator?: string; addTags?: string[] },
) {
  await rowMenu(page, name, 'Edit');
  const panel = page.getByRole('dialog');
  if (changes.title !== undefined) {
    await panel.getByPlaceholder('Title-video').fill(changes.title);
  }
  if (changes.creator !== undefined) {
    await panel.locator('section').filter({ hasText: 'Creator:' }).locator('input').fill(changes.creator);
  }
  const tagInput = panel.locator('app-tag-chip-input input');
  for (const tag of changes.addTags ?? []) {
    await tagInput.fill(tag);
    await tagInput.press('Enter');
  }
  // Moving focus away closes any suggestion list still covering the buttons. Not Escape:
  // with no list open, it would close the dialog itself.
  await panel.getByRole('heading').click();
  await panel.getByRole('button', { name: 'Save' }).click();
  await panel.waitFor({ state: 'detached' });
}
