import { expect, Page, test } from '@playwright/test';
import { content, editVideo, listedNames, openDirectory, row, tagsOf } from '../support/file-browser';

/*
  Batch operations act on several videos at once and report progress over a
  subscription. Each test uses only its own seeded directory of Local-resource/Resource-1.
*/

/** Selects the videos by clicking their rows, then picks `action` from the batch menu. */
async function batch(page: Page, videos: string[], action: 'Edit' | 'Delete') {
  for (const video of videos) {
    await row(page, video).click();
  }
  // A short timeout: a toast covering the button would otherwise only show up as a
  // ten-second wait until it fades.
  await content(page).getByRole('button', { name: 'Options' }).click({ timeout: 2_000 });
  await page.getByRole('menuitem', { name: `Batch (${videos.length})` }).click();
  await page.getByRole('menuitem', { name: action }).click();
}

test('tags added and removed in a batch reach every selected video and only those', async ({ page }) => {
  /*
    Given Local-resource/Resource-1/batch-tags holds "harbor", "lighthouse" and "pier"
    And "harbor" is tagged "draft", "lighthouse" is tagged "draft" and "coast", and "pier" has no tags
    When the user selects "harbor" and "lighthouse" and, in a batch edit, adds tag "coast" and removes tag "draft"
      (right away, while the toasts saying the edits were saved still show)
    Then "harbor" and "lighthouse" are both tagged "coast" only
    And "pier" still has no tags
    When the page is reloaded
    Then the tags are still as above
  */
  await openDirectory(page, 'Local-resource', 'Resource-1', 'batch-tags');
  await editVideo(page, 'harbor', { addTags: ['draft'] });
  await editVideo(page, 'lighthouse', { addTags: ['draft', 'coast'] });
  await expect.poll(() => tagsOf(page, 'lighthouse')).toEqual(['coast', 'draft']);
  // Stated so the next step really runs while the toasts are up.
  await expect(page.locator('app-toast-displayer div.border-green-500').first()).toBeVisible();

  await batch(page, ['harbor', 'lighthouse'], 'Edit');
  const panel = page.getByRole('dialog');
  // The tag lists sit in a section that starts collapsed.
  await panel.getByRole('button', { name: /^Tags/ }).click();
  for (const [placeholder, tag] of [['Enter a tag to add', 'coast'], ['Enter a tag to remove', 'draft']]) {
    // The tag input's host element carries the placeholder too, so match the <input> only.
    const input = panel.locator(`input[placeholder="${placeholder}"]`);
    await input.fill(tag);
    await input.press('Enter');
  }
  // Moving focus away closes a suggestion list still covering the buttons.
  await panel.getByRole('heading').click();
  await panel.getByRole('button', { name: 'Edit', exact: true }).click();
  await panel.waitFor({ state: 'detached' });

  const expectTags = async () => {
    await expect.poll(() => tagsOf(page, 'harbor')).toEqual(['coast']);
    await expect.poll(() => tagsOf(page, 'lighthouse')).toEqual(['coast']);
    await expect.poll(() => tagsOf(page, 'pier')).toEqual([]);
  };
  await expectTags();

  await page.reload();
  await expectTags();
});

test('videos deleted in a batch leave the listing for good, and only those', async ({ page }) => {
  /*
    Given Local-resource/Resource-1/batch-delete holds "ferry", "dock" and "buoy"
    When the user selects "ferry" and "buoy" and deletes them in a batch, confirming
    Then only "dock" is listed
    When the page is reloaded
    Then only "dock" is listed
  */
  await openDirectory(page, 'Local-resource', 'Resource-1', 'batch-delete');
  await expect.poll(() => listedNames(page)).toEqual(['buoy', 'dock', 'ferry']);

  await batch(page, ['ferry', 'buoy'], 'Delete');
  await page.getByRole('dialog').getByRole('button', { name: 'Yes' }).click();

  await expect.poll(() => listedNames(page)).toEqual(['dock']);
  await page.reload();
  await expect.poll(() => listedNames(page)).toEqual(['dock']);
});
