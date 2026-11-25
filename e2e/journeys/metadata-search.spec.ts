import { expect, test } from '@playwright/test';
import { cell, content, editVideo, openDirectory, tagsOf } from '../support/file-browser';

/*
  Metadata written in the file browser is what the search page and the player read.
  Uses only the seeded "editing" directory of Local-resource/Resource-1.
*/

test('a video edited in the file browser is found by the search page and shows its new details', async ({ page, context }) => {
  /*
    Given Local-resource/Resource-1/editing holds "postcard.mp4", never edited
    When the user edits "postcard" in the file browser: title "Sunset postcard", creator "Ana", tags "beach" and "summer"
    Then its row shows title "Sunset postcard", creator "Ana" and tags "beach" and "summer"
    When the user searches for title "Sunset" by creator "Ana" on the search page
    Then "Sunset postcard" is the only result
    When the user opens it from the results
    Then the player page shows "Sunset postcard" by "Ana", tagged "beach" and "summer"
  */
  await openDirectory(page, 'Local-resource', 'Resource-1', 'editing');
  await editVideo(page, 'postcard', { title: 'Sunset postcard', creator: 'Ana', addTags: ['beach', 'summer'] });

  await expect(await cell(page, 'Sunset postcard', 'Author')).toHaveText('Ana');
  await expect.poll(() => tagsOf(page, 'Sunset postcard')).toEqual(['beach', 'summer']);

  await page.goto('/search');
  const [title, creator] = await content(page).locator('input[type="text"]').all();
  await title.fill('Sunset');
  await creator.fill('Ana');
  await content(page).locator('button:has(> mat-icon[fonticon="search"])').click();
  const results = content(page).locator('app-video-card p.font-semibold');
  await expect(results).toHaveText(['Sunset postcard']);

  const [player] = await Promise.all([context.waitForEvent('page'), results.first().click()]);
  await expect(player.getByRole('heading', { name: 'Sunset postcard', exact: true })).toBeVisible();
  await expect(player.getByText('Creator:').locator('xpath=following-sibling::a')).toHaveText('Ana');
  const tags = player.getByText('Tags:').locator('xpath=following-sibling::a');
  await expect.poll(async () => (await tags.allInnerTexts()).map(t => t.trim()).sort()).toEqual(['beach', 'summer']);
});
