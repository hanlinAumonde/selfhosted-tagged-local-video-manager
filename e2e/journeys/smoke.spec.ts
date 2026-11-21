import { expect, test } from '@playwright/test';
import { content, openDirectory } from '../support/file-browser';

/*
  Technical check of the e2e stack: one pass through every layer a journey relies on
  (nginx -> GraphQL -> storage -> Mongo, ffmpeg thumbnails stored in rustfs, video
  streaming). Uses only the seeded "smoke" directory of Local-resource/Resource-1.
*/

test('a seeded video can be found in the file browser and played', async ({ page, context }) => {
  /*
    Given Local-resource/Resource-1 holds directory "smoke" with "first.mp4" and "second.mp4"
    When the user opens the file browser and goes into Local-resource / Resource-1 / smoke
    Then videos "first" and "second" are listed
    When the user switches to the grid view
    Then both videos show a thumbnail
    When the user plays "first"
    Then the player page shows "first"
    And the video plays
    And its view count goes from 0 to 1
  */
  await openDirectory(page, 'Local-resource', 'Resource-1', 'smoke');
  const main = content(page);
  // The file browser shows a video by its name, which is the file name without extension.
  await expect(main.getByText('first', { exact: true })).toBeVisible();
  await expect(main.getByText('second', { exact: true })).toBeVisible();

  await page.locator('button:has(mat-icon[fonticon="grid_view"])').click();
  const thumbnails = page.locator('app-file-thumbnail img');
  await expect(thumbnails).toHaveCount(2);
  // The placeholder is a static icon; a blob URL means ffmpeg produced the frame and it
  // came back through the backend.
  for (const thumbnail of await thumbnails.all()) {
    await expect(thumbnail).toHaveAttribute('src', /^blob:/);
  }

  await main.getByText('first', { exact: true }).click({ button: 'right' });
  const [player] = await Promise.all([
    context.waitForEvent('page'),
    page.getByRole('link', { name: 'Play Video' }).click(),
  ]);

  await expect(player.getByRole('heading', { name: 'first', exact: true })).toBeVisible();
  const views = player.getByText('Views:').locator('xpath=following-sibling::span');
  await expect(views).toHaveText('0');

  await player.getByRole('button', { name: /^play/i }).first().click();
  await expect
    .poll(() => player.locator('video').evaluate((v: HTMLVideoElement) => v.currentTime), {
      message: 'the video is playing',
    })
    .toBeGreaterThan(0);
  await expect(views).toHaveText('1');
});
